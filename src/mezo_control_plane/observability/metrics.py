from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Final

from mezo_control_plane.queue.metrics import QueueMetricsSnapshot

_UUID_SEGMENT: Final = re.compile(
    r"/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}"
)
_NUMBER_SEGMENT: Final = re.compile(r"/(?P<number>[0-9]+)(?=/|$)")


@dataclass(frozen=True)
class RequestMetric:
    method: str
    route: str
    status: int
    count: int
    duration_seconds: float


@dataclass(frozen=True)
class ApplicationMetricsSnapshot:
    requests: tuple[RequestMetric, ...]


class MetricsRegistry:
    """Small process-local metrics registry with bounded route labels."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[tuple[str, str, int], int] = {}
        self._durations: dict[tuple[str, str, int], float] = {}

    def observe_request(self, method: str, route: str, status: int, seconds: float) -> None:
        key = (method.upper(), normalize_route(route), status)
        with self._lock:
            self._counts[key] = self._counts.get(key, 0) + 1
            self._durations[key] = self._durations.get(key, 0.0) + max(seconds, 0.0)

    def snapshot(self) -> ApplicationMetricsSnapshot:
        with self._lock:
            requests = tuple(
                RequestMetric(
                    method=method,
                    route=route,
                    status=status,
                    count=count,
                    duration_seconds=self._durations[(method, route, status)],
                )
                for (method, route, status), count in sorted(self._counts.items())
            )
        return ApplicationMetricsSnapshot(requests=requests)


def normalize_route(path: str) -> str:
    normalized = _UUID_SEGMENT.sub("/{id}", path)
    return _NUMBER_SEGMENT.sub("/{number}", normalized)[:256]


def render_prometheus(
    application: ApplicationMetricsSnapshot,
    queue: QueueMetricsSnapshot | None,
) -> str:
    lines = [
        "# HELP mezo_http_requests_total Total HTTP requests.",
        "# TYPE mezo_http_requests_total counter",
        "# HELP mezo_http_request_duration_seconds_total Total HTTP request duration.",
        "# TYPE mezo_http_request_duration_seconds_total counter",
    ]
    for item in application.requests:
        labels = _labels(method=item.method, route=item.route, status=str(item.status))
        lines.append(f"mezo_http_requests_total{{{labels}}} {item.count}")
        lines.append(
            f"mezo_http_request_duration_seconds_total{{{labels}}} "
            f"{item.duration_seconds:.9f}"
        )

    if queue is not None:
        lines.extend(
            [
                "# HELP mezo_queue_ready_tasks Ready queue depth by priority.",
                "# TYPE mezo_queue_ready_tasks gauge",
            ]
        )
        for priority, depth in sorted(queue.ready_depth.items()):
            lines.append(
                f'mezo_queue_ready_tasks{{priority="{_escape(priority)}"}} {depth}'
            )
        queue_values: tuple[tuple[str, int | float | None], ...] = (
            ("mezo_queue_inflight_tasks", queue.inflight),
            ("mezo_queue_active_leases", queue.leases),
            ("mezo_queue_expired_lease_candidates", queue.expired_lease_candidates),
            ("mezo_queue_delayed_retries", queue.delayed_retries),
            ("mezo_queue_dead_letters", queue.dead_letters),
            ("mezo_workers_active", queue.active_workers),
            ("mezo_workers_draining", queue.draining_workers),
            ("mezo_executions_active", queue.active_executions),
            ("mezo_queue_oldest_ready_age_seconds", queue.oldest_ready_age_seconds),
            ("mezo_queue_claim_latency_seconds", queue.claim_latency_seconds),
            ("mezo_queue_execution_latency_seconds", queue.execution_latency_seconds),
        )
        for name, value in queue_values:
            if value is not None:
                lines.append(f"# TYPE {name} gauge")
                lines.append(f"{name} {value}")
        for name, value in sorted(queue.counters.items()):
            lines.append(
                f'mezo_queue_events_total{{event="{_escape(name)}"}} {value}'
            )
    return "\n".join(lines) + "\n"


def _labels(**values: str) -> str:
    return ",".join(f'{name}="{_escape(value)}"' for name, value in values.items())


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
