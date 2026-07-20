from fastapi import APIRouter, Depends, status
from redis.asyncio import Redis

from mezo_control_plane.api.dependencies import require_api_key
from mezo_control_plane.core.domain import TaskRecord, TaskRequest
from mezo_control_plane.core.settings import get_settings
from mezo_control_plane.queue.tasks import TaskQueue

router = APIRouter(prefix="/v1/tasks", tags=["tasks"], dependencies=[Depends(require_api_key)])


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def submit_task(request: TaskRequest) -> TaskRecord:
    task = TaskRecord(request=request)
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url)
    try:
        await TaskQueue(redis).enqueue(task)
    finally:
        await redis.aclose()
    return task
