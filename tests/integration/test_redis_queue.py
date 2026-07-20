import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from mezo_control_plane.core.domain import TaskRecord, TaskRequest
from mezo_control_plane.queue.cancellation import CancellationResult, CancellationService
from mezo_control_plane.queue.consumer import TaskConsumer
from mezo_control_plane.queue.dead_letter_queue import DeadLetterQueue, DeadLetterRecord
from mezo_control_plane.queue.metrics import QueueMetricsCollector
from mezo_control_plane.queue.priorities import TaskPriority
from mezo_control_plane.queue.producer import TaskProducer
from mezo_control_plane.queue.recovery import LeaseRecovery
from mezo_control_plane.queue.retry_policy import RetryPolicy
from mezo_control_plane.queue.retry_scheduler import RetryScheduler
from mezo_control_plane.worker.failure_classification import ExecutionFailure, FailureClass
from mezo_control_plane.worker.registration import WorkerRegistry


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


async def test_expired_lease_is_recovered_once(redis_queue: tuple[Redis, str]) -> None:
    redis, prefix = redis_queue
    await TaskProducer(redis, prefix).enqueue(task(), "submission-recovery")
    claimed = await TaskConsumer(redis, "worker-a", prefix).claim(visibility_seconds=0)
    assert claimed is not None
    recovery = LeaseRecovery(redis, prefix)
    assert (await recovery.recover_expired()).recovered == 1
    assert (await recovery.recover_expired()).recovered == 0


async def test_priority_ordering(redis_queue: tuple[Redis, str]) -> None:
    redis, prefix = redis_queue
    producer = TaskProducer(redis, prefix)
    await producer.enqueue(task(), "low", TaskPriority.LOW)
    await producer.enqueue(task(), "critical", TaskPriority.CRITICAL)
    consumer = TaskConsumer(redis, "worker", prefix)
    first = await consumer.claim()
    second = await consumer.claim()
    assert first is not None and second is not None
    assert first.message_id != second.message_id
    first_envelope = json.loads(await redis.hget(f"{prefix}:inflight", first.message_id))
    second_envelope = json.loads(await redis.hget(f"{prefix}:inflight", second.message_id))
    assert [first_envelope["priority"], second_envelope["priority"]] == [0, 3]


async def test_concurrent_recovery_creates_one_retry(redis_queue: tuple[Redis, str]) -> None:
    redis, prefix = redis_queue
    await TaskProducer(redis, prefix).enqueue(task(), "concurrent-recovery")
    claimed = await TaskConsumer(redis, "crashed", prefix).claim(visibility_seconds=0)
    assert claimed is not None
    first, second = await __import__("asyncio").gather(
        LeaseRecovery(redis, prefix).recover_expired(),
        LeaseRecovery(redis, prefix).recover_expired(),
    )
    assert first.recovered + second.recovered == 1
    assert await redis.hlen(f"{prefix}:delayed") == 1


async def test_renewed_lease_is_not_recovered(redis_queue: tuple[Redis, str]) -> None:
    redis, prefix = redis_queue
    await TaskProducer(redis, prefix).enqueue(task(), "renew-race")
    consumer = TaskConsumer(redis, "worker", prefix)
    claimed = await consumer.claim(visibility_seconds=1)
    assert claimed is not None
    await redis.zadd(f"{prefix}:lease-expiry", {claimed.message_id: 0})
    assert await consumer.renew_lease(claimed, visibility_seconds=30)
    result = await LeaseRecovery(redis, prefix).recover_expired(
        now=datetime.now(UTC) + timedelta(seconds=2)
    )
    assert result.recovered == 0
    assert await redis.hget(f"{prefix}:inflight", claimed.message_id)


async def test_orphan_expiry_is_cleaned(redis_queue: tuple[Redis, str]) -> None:
    redis, prefix = redis_queue
    await redis.zadd(f"{prefix}:lease-expiry", {"orphan": 0})
    result = await LeaseRecovery(redis, prefix).recover_expired()
    assert result.orphan_cleaned == 1
    assert await redis.zcard(f"{prefix}:lease-expiry") == 0


async def test_retry_schedule_and_atomic_promotion(redis_queue: tuple[Redis, str]) -> None:
    redis, prefix = redis_queue
    result = await TaskProducer(redis, prefix).enqueue(task(), "retry")
    raw = await redis.lpop(f"{prefix}:ready:{int(TaskPriority.NORMAL)}")
    envelope = json.loads(raw)
    scheduler = RetryScheduler(
        redis, prefix, RetryPolicy(base_delay_seconds=1, jitter_ratio=0)
    )
    failure = ExecutionFailure(FailureClass.RETRYABLE_PROVIDER, "temporary", True)
    scheduled = await scheduler.schedule_failure(envelope, failure)
    assert scheduled.scheduled and scheduled.record is not None
    assert scheduled.record.message_id == result.message_id
    future = await scheduler.promote_due(now=datetime.now(UTC))
    assert future.promoted == 0
    due_at = scheduled.record.due_at + timedelta(seconds=1)
    first, second = await __import__("asyncio").gather(
        scheduler.promote_due(now=due_at), scheduler.promote_due(now=due_at)
    )
    assert first.promoted + second.promoted == 1
    assert await redis.llen(f"{prefix}:ready:{int(TaskPriority.NORMAL)}") == 1


async def test_retry_after_overrides_backoff(redis_queue: tuple[Redis, str]) -> None:
    redis, prefix = redis_queue
    await TaskProducer(redis, prefix).enqueue(task(), "retry-after")
    raw = await redis.lpop(f"{prefix}:ready:{int(TaskPriority.NORMAL)}")
    now = datetime.now(UTC)
    failure = ExecutionFailure(FailureClass.RATE_LIMITED, "limited", True, 25)
    scheduled = await RetryScheduler(redis, prefix).schedule_failure(
        json.loads(raw), failure, now=now
    )
    assert scheduled.record is not None
    assert scheduled.record.due_at == now + timedelta(seconds=25)


async def test_typed_dlq_finalize_and_single_replay(redis_queue: tuple[Redis, str]) -> None:
    redis, prefix = redis_queue
    await TaskProducer(redis, prefix).enqueue(task(), "dlq")
    envelope = json.loads(await redis.lpop(f"{prefix}:ready:{int(TaskPriority.NORMAL)}"))
    record = DeadLetterRecord(
        message_id=envelope["message_id"],
        task_id=envelope["task_id"],
        envelope=envelope,
        priority=envelope["priority"],
        attempts=5,
        failure_class="retry_exhaustion",
        error_summary="exhausted",
        source_operation="execution",
        replay_eligible=True,
    )
    dlq = DeadLetterQueue(redis, prefix)
    first = await dlq.finalize(record)
    duplicate = await dlq.finalize(record.model_copy(update={"error_summary": "changed"}))
    assert duplicate.error_summary == first.error_summary
    await dlq.approve_replay(first.id, True)
    one, two = await __import__("asyncio").gather(dlq.replay(first.id), dlq.replay(first.id))
    assert sorted([one[0].value, two[0].value]) == ["already-replayed", "replayed"]
    updated = await dlq.get(first.id)
    assert updated is not None and updated.replayed_message_id != first.message_id
    assert updated.attempts == 5


async def test_cancellation_blocks_claim_ack_and_retry(redis_queue: tuple[Redis, str]) -> None:
    redis, prefix = redis_queue
    queued = task()
    await TaskProducer(redis, prefix).enqueue(queued, "cancel-ready")
    cancellation = CancellationService(redis, prefix)
    assert await cancellation.cancel(str(queued.id), "operator", "stop") == "cancelled"
    assert await TaskConsumer(redis, "worker", prefix).claim() is None
    assert await cancellation.cancel(str(queued.id)) == "already_cancelled"

    inflight = task()
    await TaskProducer(redis, prefix).enqueue(inflight, "cancel-inflight")
    consumer = TaskConsumer(redis, "worker", prefix)
    claimed = await consumer.claim()
    assert claimed is not None
    assert await cancellation.cancel(str(inflight.id)) is CancellationResult.CANCELLED
    assert not await consumer.renew_lease(claimed)
    assert not await consumer.acknowledge(claimed)


async def test_cancellation_removes_delayed_retry(redis_queue: tuple[Redis, str]) -> None:
    redis, prefix = redis_queue
    item = task()
    await TaskProducer(redis, prefix).enqueue(item, "cancel-delayed")
    envelope = json.loads(await redis.lpop(f"{prefix}:ready:{int(TaskPriority.NORMAL)}"))
    scheduler = RetryScheduler(redis, prefix)
    scheduled = await scheduler.schedule_failure(
        envelope, ExecutionFailure(FailureClass.RETRYABLE_PROVIDER, "temporary", True)
    )
    assert scheduled.scheduled
    await CancellationService(redis, prefix).cancel(str(item.id))
    assert await redis.hlen(f"{prefix}:delayed") == 0
    assert (await scheduler.promote_due(now=datetime.now(UTC) + timedelta(days=1))).promoted == 0


async def test_worker_registration_and_metrics_are_non_destructive(
    redis_queue: tuple[Redis, str],
) -> None:
    redis, prefix = redis_queue
    registry = WorkerRegistry(redis, "worker", 3, prefix=prefix)
    await registry.heartbeat(active_count=2, draining=True, ttl_seconds=30)
    await TaskProducer(redis, prefix).enqueue(task(), "metrics")
    before = await redis.llen(f"{prefix}:ready:{int(TaskPriority.NORMAL)}")
    snapshot = await QueueMetricsCollector(redis, prefix).snapshot()
    after = await redis.llen(f"{prefix}:ready:{int(TaskPriority.NORMAL)}")
    assert before == after == 1
    assert snapshot.active_workers == 1
    assert snapshot.draining_workers == 1
    assert snapshot.active_executions == 2
    assert snapshot.ready_depth["normal"] == 1
