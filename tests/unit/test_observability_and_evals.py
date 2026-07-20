from datetime import UTC, datetime
from uuid import uuid4

import pytest

from mezo_control_plane.evals.cases import default_cases
from mezo_control_plane.evals.runner import run_suite
from mezo_control_plane.observability.alerts import evaluate_alerts, queue_metric_values
from mezo_control_plane.observability.evidence import EvidenceLedger, LedgerEntry
from mezo_control_plane.observability.metrics import (
    MetricsRegistry,
    normalize_route,
    render_prometheus,
)
from mezo_control_plane.observability.tracing import current_trace, tracing_boundary
from mezo_control_plane.queue.metrics import QueueMetricsSnapshot


def queue_snapshot() -> QueueMetricsSnapshot:
    return QueueMetricsSnapshot(
        ready_depth={"high": 120},
        inflight=2,
        leases=2,
        expired_lease_candidates=1,
        delayed_retries=3,
        dead_letters=1,
        active_workers=0,
        draining_workers=0,
        active_executions=0,
        oldest_ready_age_seconds=400,
    )


def test_prometheus_metrics_bound_route_cardinality() -> None:
    registry = MetricsRegistry()
    registry.observe_request(
        "GET", "/v1/tasks/123e4567-e89b-42d3-a456-426614174000", 200, 0.25
    )
    rendered = render_prometheus(registry.snapshot(), queue_snapshot())
    assert '/v1/tasks/{id}' in rendered
    assert "123e4567" not in rendered
    assert "mezo_queue_dead_letters 1" in rendered
    assert normalize_route("/runs/123/logs") == "/runs/{number}/logs"


def test_alert_rules_detect_backlog_workers_dead_letters_and_stale_tasks() -> None:
    values = queue_metric_values(queue_snapshot())
    firing = {item.name for item in evaluate_alerts(values) if item.firing}
    assert {
        "queue-backlog-high",
        "queue-oldest-task-stale",
        "dead-letter-present",
        "expired-leases-present",
        "workers-unavailable-with-backlog",
    } <= firing


def test_trace_boundary_redacts_sensitive_attributes(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("INFO", logger="mezo.trace"):
        with tracing_boundary("model.call", {"api_token": "do-not-log", "provider": "gemini"}):
            assert current_trace() is not None
    assert current_trace() is None
    assert "do-not-log" not in caplog.text


def test_evidence_ledger_detects_tampering() -> None:
    ledger = EvidenceLedger()
    first = ledger.append(uuid4(), "test", "unit tests passed", {"count": 100})
    ledger.append(first.task_id, "guard", "security guard passed")
    assert ledger.verify()
    tampered = first.model_copy(update={"summary": "tests skipped"})
    with pytest.raises(ValueError, match="Invalid evidence ledger chain"):
        EvidenceLedger((tampered, *ledger.entries[1:]))


def test_ledger_hash_is_stable_for_same_record() -> None:
    task_id = uuid4()
    timestamp = datetime(2026, 7, 20, tzinfo=UTC)
    first = EvidenceLedger().append(task_id, "test", "passed", created_at=timestamp)
    restored = LedgerEntry.model_validate(first.model_dump())
    assert EvidenceLedger((restored,)).verify()


def test_adversarial_eval_suite_detects_all_expected_failures() -> None:
    result = run_suite(default_cases())
    assert result.total >= 10
    assert result.failed == 0
    rejected_reasons = {
        reason
        for item in result.cases
        if not item.decision.accepted
        for reason in item.decision.reasons
    }
    assert "success_claim_without_passing_tests" in rejected_reasons
    assert "protected_branch_write_attempt" in rejected_reasons
    assert any(reason.startswith("unknown_tool:") for reason in rejected_reasons)


def test_database_urls_are_normalized_for_runtime_and_migrations() -> None:
    from mezo_control_plane.database.urls import async_database_url, sync_database_url

    plain = "postgres://user:password@database.internal:5432/mezo"
    assert async_database_url(plain).startswith("postgresql+asyncpg://")
    assert sync_database_url(plain).startswith("postgresql+psycopg://")
    assert sync_database_url(async_database_url(plain)).startswith("postgresql+psycopg://")


def test_trace_boundary_normalizes_untrusted_trace_identifier(
    caplog: pytest.LogCaptureFixture,
) -> None:
    supplied = "attacker-controlled\ntrace"
    with caplog.at_level("INFO", logger="mezo.trace"):
        with tracing_boundary("http.request", trace_id=supplied) as context:
            assert len(context.trace_id) == 32
            assert context.trace_id != supplied
    assert supplied not in caplog.text


def test_evidence_ledger_rejects_mixed_task_identifiers() -> None:
    ledger = EvidenceLedger()
    ledger.append(uuid4(), "test", "first task")
    with pytest.raises(ValueError, match="cannot mix task identifiers"):
        ledger.append(uuid4(), "test", "second task")


def test_alerts_mark_unpublished_metrics_unavailable() -> None:
    evaluations = evaluate_alerts(queue_metric_values(queue_snapshot()))
    unavailable = {item.metric for item in evaluations if not item.available}
    assert {
        "providers.unhealthy",
        "tasks.repeated_failures",
        "model.cost_usd_hour",
    } <= unavailable
    assert all(not item.firing for item in evaluations if not item.available)
    assert all(item.value is None for item in evaluations if not item.available)
