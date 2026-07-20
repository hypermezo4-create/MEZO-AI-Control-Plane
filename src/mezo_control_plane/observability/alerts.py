from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from pydantic import BaseModel, Field

from mezo_control_plane.queue.metrics import QueueMetricsSnapshot


class AlertSeverity(StrEnum):
    WARNING = "warning"
    CRITICAL = "critical"


class AlertOperator(StrEnum):
    GREATER_THAN_OR_EQUAL = "gte"
    LESS_THAN_OR_EQUAL = "lte"


class AlertRule(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    metric: str = Field(min_length=1, max_length=128)
    operator: AlertOperator
    threshold: float
    severity: AlertSeverity
    summary: str = Field(min_length=1, max_length=500)


class AlertEvaluation(BaseModel):
    name: str
    metric: str
    value: float | None
    available: bool
    threshold: float
    severity: AlertSeverity
    summary: str
    firing: bool


DEFAULT_ALERT_RULES: tuple[AlertRule, ...] = (
    AlertRule(
        name="queue-backlog-high",
        metric="queue.ready_total",
        operator=AlertOperator.GREATER_THAN_OR_EQUAL,
        threshold=100,
        severity=AlertSeverity.WARNING,
        summary="Ready queue backlog is above the operating threshold.",
    ),
    AlertRule(
        name="queue-oldest-task-stale",
        metric="queue.oldest_ready_age_seconds",
        operator=AlertOperator.GREATER_THAN_OR_EQUAL,
        threshold=300,
        severity=AlertSeverity.CRITICAL,
        summary="The oldest ready task has exceeded the queue latency objective.",
    ),
    AlertRule(
        name="dead-letter-present",
        metric="queue.dead_letters",
        operator=AlertOperator.GREATER_THAN_OR_EQUAL,
        threshold=1,
        severity=AlertSeverity.CRITICAL,
        summary="At least one task is in the dead-letter queue.",
    ),
    AlertRule(
        name="expired-leases-present",
        metric="queue.expired_lease_candidates",
        operator=AlertOperator.GREATER_THAN_OR_EQUAL,
        threshold=1,
        severity=AlertSeverity.WARNING,
        summary="Expired task leases require recovery.",
    ),
    AlertRule(
        name="workers-unavailable-with-backlog",
        metric="queue.workers_unavailable_with_backlog",
        operator=AlertOperator.GREATER_THAN_OR_EQUAL,
        threshold=1,
        severity=AlertSeverity.CRITICAL,
        summary="No active worker is available while tasks are queued.",
    ),
    AlertRule(
        name="provider-outage",
        metric="providers.unhealthy",
        operator=AlertOperator.GREATER_THAN_OR_EQUAL,
        threshold=1,
        severity=AlertSeverity.CRITICAL,
        summary="One or more required model providers are unavailable.",
    ),
    AlertRule(
        name="repeated-task-failures",
        metric="tasks.repeated_failures",
        operator=AlertOperator.GREATER_THAN_OR_EQUAL,
        threshold=3,
        severity=AlertSeverity.WARNING,
        summary="Repeated task failures crossed the review threshold.",
    ),
    AlertRule(
        name="model-cost-anomaly",
        metric="model.cost_usd_hour",
        operator=AlertOperator.GREATER_THAN_OR_EQUAL,
        threshold=25,
        severity=AlertSeverity.WARNING,
        summary="Hourly model cost crossed the configured anomaly threshold.",
    ),
)


def queue_metric_values(snapshot: QueueMetricsSnapshot) -> dict[str, float]:
    ready_total = float(sum(snapshot.ready_depth.values()))
    return {
        "queue.ready_total": ready_total,
        "queue.oldest_ready_age_seconds": float(snapshot.oldest_ready_age_seconds or 0),
        "queue.dead_letters": float(snapshot.dead_letters),
        "queue.expired_lease_candidates": float(snapshot.expired_lease_candidates),
        "queue.workers_unavailable_with_backlog": float(
            ready_total > 0 and snapshot.active_workers == 0
        ),
    }


def evaluate_alerts(
    values: Mapping[str, float],
    rules: tuple[AlertRule, ...] = DEFAULT_ALERT_RULES,
) -> tuple[AlertEvaluation, ...]:
    evaluations: list[AlertEvaluation] = []
    for rule in rules:
        raw_value = values.get(rule.metric)
        available = raw_value is not None
        value = float(raw_value) if raw_value is not None else None
        firing = False
        if value is not None:
            firing = (
                value >= rule.threshold
                if rule.operator is AlertOperator.GREATER_THAN_OR_EQUAL
                else value <= rule.threshold
            )
        evaluations.append(
            AlertEvaluation(
                name=rule.name,
                metric=rule.metric,
                value=value,
                available=available,
                threshold=rule.threshold,
                severity=rule.severity,
                summary=rule.summary,
                firing=firing,
            )
        )
    return tuple(evaluations)
