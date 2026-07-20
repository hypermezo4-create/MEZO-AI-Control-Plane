import json
from typing import Any, cast
from uuid import uuid4

from redis.asyncio import Redis

from mezo_control_plane.core.domain import TaskRecord
from mezo_control_plane.queue.deduplication import task_deduplication_key
from mezo_control_plane.queue.priorities import TaskPriority


class DuplicateTaskError(Exception):
    pass


class TaskProducer:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def enqueue(
        self,
        task: TaskRecord,
        idempotency_key: str,
        priority: TaskPriority = TaskPriority.NORMAL,
    ) -> str:
        dedupe = task_deduplication_key(idempotency_key)
        accepted = await self._redis.set(
            f"mezo:queue:dedupe:{dedupe}", str(task.id), nx=True, ex=86_400
        )
        if not accepted:
            raise DuplicateTaskError("Task submission was already accepted")
        envelope = {"task": task.model_dump(mode="json"), "attempt": 0, "message_id": str(uuid4())}
        await cast(
            Any, self._redis.rpush(f"mezo:queue:ready:{int(priority)}", json.dumps(envelope))
        )
        return str(envelope["message_id"])
