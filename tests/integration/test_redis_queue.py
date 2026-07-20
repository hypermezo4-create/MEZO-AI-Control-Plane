import os
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from mezo_control_plane.core.domain import TaskRecord, TaskRequest
from mezo_control_plane.queue.consumer import TaskConsumer
from mezo_control_plane.queue.priorities import TaskPriority
from mezo_control_plane.queue.producer import TaskProducer


@pytest.fixture
async def redis_queue() -> Redis:
    url = os.getenv("REDIS_TEST_URL")
    if not url:
        pytest.skip("REDIS_TEST_URL is not configured for real Redis integration tests")
    redis = Redis.from_url(url, decode_responses=True)
    await redis.ping()
    prefix = f"mezo:test:{uuid4()}"
    yield redis, prefix  # type: ignore[misc]
    keys = [key async for key in redis.scan_iter(match=f"{prefix}:*")]
    if keys:
        await redis.delete(*keys)
    await redis.aclose()


def task() -> TaskRecord:
    request = TaskRequest(repository="owner/repository", instruction="Inspect failure")
    return TaskRecord(request=request)


async def test_empty_queue_claim_does_not_operate_on_metadata_hash(
    redis_queue: tuple[Redis, str],
) -> None:
    redis, prefix = redis_queue
    assert await TaskConsumer(redis, "worker-a", prefix).claim() is None


async def test_enqueue_claim_lease_and_owner_acknowledgement(
    redis_queue: tuple[Redis, str],
) -> None:
    redis, prefix = redis_queue
    producer = TaskProducer(redis, prefix)
    first = await producer.enqueue(task(), "submission-1", TaskPriority.HIGH)
    duplicate = await producer.enqueue(task(), "submission-1", TaskPriority.HIGH)

    assert first.accepted
    assert not duplicate.accepted
    assert duplicate.message_id == first.message_id
    claimed = await TaskConsumer(redis, "worker-a", prefix).claim()
    assert claimed is not None
    assert await redis.hget(f"{prefix}:leases", claimed.message_id) is not None
    assert not await TaskConsumer(redis, "worker-b", prefix).acknowledge(claimed)
    assert await TaskConsumer(redis, "worker-a", prefix).acknowledge(claimed)
    assert await redis.hget(f"{prefix}:leases", claimed.message_id) is None


async def test_wrong_owner_cannot_renew_lease(redis_queue: tuple[Redis, str]) -> None:
    redis, prefix = redis_queue
    producer = TaskProducer(redis, prefix)
    await producer.enqueue(task(), "submission-2")
    claimed = await TaskConsumer(redis, "worker-a", prefix).claim()
    assert claimed is not None
    assert not await TaskConsumer(redis, "worker-b", prefix).renew_lease(claimed)
    assert await TaskConsumer(redis, "worker-a", prefix).renew_lease(claimed)
