from enum import StrEnum
from typing import Any, cast

from redis.asyncio import Redis

from mezo_control_plane.queue.producer import QueueInfrastructureError


class CancellationResult(StrEnum):
    CANCELLED = "cancelled"
    ALREADY_CANCELLED = "already_cancelled"


class CancellationService:
    def __init__(self, redis: Redis, prefix: str = "mezo:queue") -> None:
        self._redis = redis
        self._prefix = prefix

    async def cancel(self, task_id: str) -> CancellationResult:
        try:
            added = await cast(Any, self._redis.sadd(f"{self._prefix}:cancelled", task_id))
        except Exception as error:
            raise QueueInfrastructureError("Redis cancellation operation failed") from error
        return CancellationResult.CANCELLED if added else CancellationResult.ALREADY_CANCELLED

    async def is_cancelled(self, task_id: str) -> bool:
        try:
            member = await cast(
                Any, self._redis.sismember(f"{self._prefix}:cancelled", task_id)
            )
            return bool(member)
        except Exception as error:
            raise QueueInfrastructureError("Redis cancellation lookup failed") from error
