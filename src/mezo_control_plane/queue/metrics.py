from dataclasses import dataclass


@dataclass(frozen=True)
class QueueMetrics:
    depth: int
    oldest_task_age_seconds: float | None
    inflight: int
    dead_letters: int
