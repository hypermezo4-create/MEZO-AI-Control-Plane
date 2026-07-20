import json
from dataclasses import dataclass
from typing import Any, cast
from uuid import uuid4

from redis.asyncio import Redis

from mezo_control_plane.core.domain import TaskRecord
from mezo_control_plane.queue.deduplication import task_deduplication_key
from mezo_control_plane.queue.priorities import TaskPriority

_ENQUEUE_SCRIPT = """
local existing=redis.call('GET', KEYS[2])
if existing then return {0, existing} end
redis.call('SET', KEYS[2], ARGV[1], 'NX', 'EX', ARGV[2])
redis.call('HSET', KEYS[3], ARGV[3], ARGV[1])
redis.call('RPUSH', KEYS[1], ARGV[4])
return {1, ARGV[1]}
"""


@dataclass(frozen=True)
class EnqueueResult:
    message_id: str
    accepted: bool


class QueueInfrastructureError(Exception):
    pass


class TaskProducer:
    """Atomic ingress boundary: a dedupe mapping is created only with its message."""

    def __init__(self, redis: Redis, prefix: str = "mezo:queue") -> None:
        self._redis = redis
        self._prefix = prefix

    async def enqueue(
        self,
        task: TaskRecord,
        idempotency_key: str,
        priority: TaskPriority = TaskPriority.NORMAL,
    ) -> EnqueueResult:
        dedupe = task_deduplication_key(idempotency_key)
        message_id = str(uuid4())
        envelope = {
            "message_id": message_id,
            "task_id": str(task.id),
            "task": task.model_dump(mode="json"),
            "attempt": 0,
            "priority": int(priority),
            "enqueued_at": task.created_at.isoformat(),
        }
        try:
            result = await cast(
                Any,
                self._redis.eval(
                    _ENQUEUE_SCRIPT,
                    3,
                    f"{self._prefix}:ready:{int(priority)}",
                    f"{self._prefix}:dedupe:{dedupe}",
                    f"{self._prefix}:task-index",
                    message_id,
                    "86400",
                    str(task.id),
                    json.dumps(envelope, separators=(",", ":")),
                ),
            )
        except Exception as error:
            raise QueueInfrastructureError("Redis enqueue operation failed") from error
        accepted, result_message_id = result
        return EnqueueResult(message_id=str(result_message_id), accepted=bool(accepted))
