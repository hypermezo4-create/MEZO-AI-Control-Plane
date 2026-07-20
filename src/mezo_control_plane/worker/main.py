import asyncio

import structlog
from redis.asyncio import Redis

from mezo_control_plane.core.settings import get_settings
from mezo_control_plane.observability.logging import configure_logging
from mezo_control_plane.queue.tasks import TaskQueue


async def worker_loop() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = structlog.get_logger("worker")
    redis = Redis.from_url(settings.redis_url)
    queue = TaskQueue(redis)
    semaphore = asyncio.Semaphore(settings.max_task_concurrency)
    try:
        async for task in queue.consume():
            async with semaphore:
                await logger.ainfo(
                    "task_claimed",
                    task_id=str(task.id),
                    repository=task.request.repository,
                    state=task.state,
                )
                # Repository checkout and remote sandbox execution are connected here.
                await logger.ainfo("task_waiting_for_executor", task_id=str(task.id))
    finally:
        await redis.aclose()


def run() -> None:
    asyncio.run(worker_loop())
