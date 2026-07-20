import asyncio
from collections.abc import Awaitable, Callable

from mezo_control_plane.queue.consumer import ClaimedTask, TaskConsumer
from mezo_control_plane.queue.heartbeat import WorkerHeartbeat
from mezo_control_plane.worker.lifecycle import WorkerLifecycle

TaskHandler = Callable[[ClaimedTask], Awaitable[None]]


class LeasedWorker:
    def __init__(
        self, consumer: TaskConsumer, heartbeat: WorkerHeartbeat, concurrency: int
    ) -> None:
        self._consumer = consumer
        self._heartbeat = heartbeat
        self._semaphore = asyncio.Semaphore(concurrency)
        self.lifecycle = WorkerLifecycle()

    async def run_once(self, handler: TaskHandler) -> bool:
        if not self.lifecycle.accepting_work:
            return False
        await self._heartbeat.beat()
        claimed = await self._consumer.claim()
        if claimed is None:
            return False
        async with self._semaphore:
            await handler(claimed)
            return await self._consumer.acknowledge(claimed)
