import random
from datetime import UTC, datetime

import pytest

from mezo_control_plane.queue.deduplication import normalize_idempotency_key, task_deduplication_key
from mezo_control_plane.queue.leases import Lease
from mezo_control_plane.queue.retry_policy import RetryPolicy
from mezo_control_plane.queue.retry_scheduler import RetryRecord


def test_idempotency_key_is_normalized_before_hashing() -> None:
    assert task_deduplication_key(" task-1 ") == task_deduplication_key("task-1")


def test_empty_idempotency_key_is_rejected() -> None:
    with pytest.raises(ValueError):
        normalize_idempotency_key("   ")


def test_lease_has_an_owner_and_future_expiry() -> None:
    lease = Lease.new("task-1", "worker-token", 30)
    assert lease.task_id == "task-1"
    assert lease.owner_token == "worker-token"  # noqa: S105


def test_retry_policy_stops_after_budget() -> None:
    random.seed(1)
    policy = RetryPolicy(maximum_attempts=2)
    assert policy.decide(1, True).retry
    assert not policy.decide(2, True).retry
    assert not policy.decide(1, False).retry


def test_retry_after_is_honored_without_jitter() -> None:
    decision = RetryPolicy(jitter_ratio=1).decide(1, True, retry_after_seconds=17)
    assert decision.retry
    assert decision.delay_seconds == 17
    assert decision.reason == "retry-after"


def test_retry_record_preserves_attempt_history() -> None:
    now = datetime.now(UTC)
    record = RetryRecord(
        message_id="message",
        task_id="task",
        envelope={"message_id": "message"},
        priority=1,
        attempt=2,
        due_at=now,
        failure_class="rate_limited",
        error_summary="rate limited",
        retry_after_source="retry-after",
        first_failed_at=now,
        latest_failed_at=now,
        history=[{"attempt": 2}],
    )
    assert record.history == [{"attempt": 2}]
