from datetime import UTC, datetime
from typing import Any, cast

from redis.asyncio import Redis


class WorkerHeartbeat:
    def __init__(self, redis: Redis, worker_id: str, ttl_seconds: int = 30) -> None:
        self._redis = redis
        self._worker_id = worker_id
        self._ttl_seconds = ttl_seconds

    async def beat(self) -> None:
        await cast(
            Any,
            self._redis.set(
                f"mezo:queue:worker:{self._worker_id}",
                datetime.now(UTC).isoformat(),
                ex=self._ttl_seconds,
            ),
        )

    async def alive(self) -> bool:
        return bool(await cast(Any, self._redis.exists(f"mezo:queue:worker:{self._worker_id}")))
