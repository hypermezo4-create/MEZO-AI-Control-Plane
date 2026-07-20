import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

from redis.asyncio import Redis

from mezo_control_plane.queue.priorities import TaskPriority
from mezo_control_plane.queue.producer import QueueInfrastructureError


@dataclass(frozen=True)
class QueueMetricsSnapshot:
    ready_depth: dict[str, int]
    inflight: int
    leases: int
    expired_lease_candidates: int
    delayed_retries: int
    dead_letters: int
    active_workers: int
    draining_workers: int
    active_executions: int
    oldest_ready_age_seconds: float | None
    counters: dict[str, int] = field(default_factory=dict)
    claim_latency_seconds: float | None = None
    execution_latency_seconds: float | None = None


class QueueMetricsCollector:
    def __init__(self, redis: Redis, prefix: str = "mezo:queue") -> None:
        self._redis = redis
        self._prefix = prefix

    async def increment(self, name: str, amount: int = 1) -> None:
        try:
            await cast(
                Any,
                self._redis.hincrby(f"{self._prefix}:metric-counters", name, amount),
            )
        except Exception as error:
            raise QueueInfrastructureError("Redis metrics update failed") from error

    async def observe(self, name: str, seconds: float) -> None:
        try:
            pipe = self._redis.pipeline(transaction=True)
            pipe.hincrbyfloat(f"{self._prefix}:metric-totals", name, seconds)
            pipe.hincrby(f"{self._prefix}:metric-samples", name, 1)
            await cast(Any, pipe.execute())
        except Exception as error:
            raise QueueInfrastructureError("Redis metric observation failed") from error

    async def snapshot(self, now: datetime | None = None) -> QueueMetricsSnapshot:
        current = now or datetime.now(UTC)
        ready_keys = [f"{self._prefix}:ready:{int(item)}" for item in TaskPriority]
        try:
            pipe = self._redis.pipeline(transaction=False)
            for key in ready_keys:
                pipe.llen(key)
                pipe.lindex(key, 0)
            pipe.hlen(f"{self._prefix}:inflight")
            pipe.hlen(f"{self._prefix}:leases")
            pipe.zcount(f"{self._prefix}:lease-expiry", "-inf", current.timestamp())
            pipe.zcard(f"{self._prefix}:delayed-due")
            pipe.hlen(f"{self._prefix}:dlq")
            pipe.hgetall(f"{self._prefix}:metric-counters")
            pipe.hgetall(f"{self._prefix}:metric-totals")
            pipe.hgetall(f"{self._prefix}:metric-samples")
            values = await cast(Any, pipe.execute())
            workers = []
            async for key in self._redis.scan_iter(match=f"{self._prefix}:workers:*"):
                raw = await cast(Any, self._redis.get(key))
                if raw:
                    workers.append(json.loads(raw))
        except Exception as error:
            raise QueueInfrastructureError("Redis metrics collection failed") from error
        ready_depth: dict[str, int] = {}
        oldest: datetime | None = None
        position = 0
        for priority in TaskPriority:
            ready_depth[priority.name.lower()] = int(values[position])
            raw = values[position + 1]
            position += 2
            if raw:
                enqueued = datetime.fromisoformat(json.loads(raw)["enqueued_at"])
                oldest = enqueued if oldest is None or enqueued < oldest else oldest
        counters = {str(key): int(value) for key, value in values[position + 5].items()}
        totals = values[position + 6]
        samples = values[position + 7]

        def average(name: str) -> float | None:
            count = int(samples.get(name, 0))
            return float(totals[name]) / count if count else None

        return QueueMetricsSnapshot(
            ready_depth=ready_depth,
            inflight=int(values[position]),
            leases=int(values[position + 1]),
            expired_lease_candidates=int(values[position + 2]),
            delayed_retries=int(values[position + 3]),
            dead_letters=int(values[position + 4]),
            active_workers=len(workers),
            draining_workers=sum(bool(worker.get("draining")) for worker in workers),
            active_executions=sum(int(worker.get("active_count", 0)) for worker in workers),
            oldest_ready_age_seconds=(current - oldest).total_seconds() if oldest else None,
            counters=counters,
            claim_latency_seconds=average("claim_latency"),
            execution_latency_seconds=average("execution_latency"),
        )


QueueMetrics = QueueMetricsSnapshot
