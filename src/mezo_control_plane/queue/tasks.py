import json
from collections.abc import AsyncIterator, Awaitable
from typing import Any, cast

from redis.asyncio import Redis

from mezo_control_plane.core.domain import TaskRecord


class TaskQueue:
    _queue_name = "mezo:tasks"

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def enqueue(self, task: TaskRecord) -> None:
        operation = cast(
            Awaitable[int],
            self._redis.rpush(self._queue_name, task.model_dump_json()),
        )
        await operation

    async def consume(self, timeout_seconds: int = 5) -> AsyncIterator[TaskRecord]:
        while True:
            operation = cast(
                Awaitable[list[Any] | None],
                self._redis.blpop([self._queue_name], timeout=timeout_seconds),
            )
            item = await operation
            if item is None:
                continue
            _, payload = item
            decoded = payload.decode() if isinstance(payload, bytes) else payload
            yield TaskRecord.model_validate(json.loads(decoded))
