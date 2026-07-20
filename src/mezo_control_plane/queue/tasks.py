import asyncio
from collections.abc import AsyncIterator

from redis.asyncio import Redis

from mezo_control_plane.core.domain import TaskRecord
from mezo_control_plane.queue.consumer import TaskConsumer
from mezo_control_plane.queue.producer import TaskProducer


class TaskQueue:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def enqueue(self, task: TaskRecord) -> None:
        await TaskProducer(self._redis).enqueue(task, str(task.id))

    async def consume(self, timeout_seconds: int = 5) -> AsyncIterator[TaskRecord]:
        consumer = TaskConsumer(self._redis, "legacy-consumer")
        while True:
            claimed = await consumer.claim()
            if claimed is None:
                await asyncio.sleep(timeout_seconds)
                continue
            yield claimed.task
            await consumer.acknowledge(claimed)
