import json
import platform
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from redis.asyncio import Redis

from mezo_control_plane.queue.producer import QueueInfrastructureError


@dataclass(frozen=True)
class WorkerRegistration:
    worker_id: str
    instance_id: str
    version: str
    started_at: str
    last_heartbeat: str
    capacity: int
    active_count: int
    draining: bool
    runtime: str


class WorkerRegistry:
    def __init__(
        self, redis: Redis, worker_id: str, capacity: int, prefix: str = "mezo:queue"
    ) -> None:
        now = datetime.now(UTC).isoformat()
        self._redis = redis
        self._prefix = prefix
        self._registration = WorkerRegistration(
            worker_id=worker_id,
            instance_id=str(uuid4()),
            version="0.1.0",
            started_at=now,
            last_heartbeat=now,
            capacity=capacity,
            active_count=0,
            draining=False,
            runtime=f"python-{platform.python_version()}",
        )

    async def heartbeat(self, active_count: int, draining: bool, ttl_seconds: int = 30) -> None:
        payload = asdict(self._registration)
        payload.update(
            last_heartbeat=datetime.now(UTC).isoformat(),
            active_count=active_count,
            draining=draining,
        )
        try:
            await cast(
                Any,
                self._redis.set(
                    f"{self._prefix}:workers:{self._registration.worker_id}",
                    json.dumps(payload, separators=(",", ":")),
                    ex=ttl_seconds,
                ),
            )
        except Exception as error:
            raise QueueInfrastructureError("Redis worker heartbeat failed") from error

    async def remove(self) -> None:
        try:
            await cast(
                Any,
                self._redis.delete(f"{self._prefix}:workers:{self._registration.worker_id}"),
            )
        except Exception as error:
            raise QueueInfrastructureError("Redis worker deregistration failed") from error
