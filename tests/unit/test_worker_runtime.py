import asyncio
from datetime import UTC, datetime, timedelta
from typing import cast

from mezo_control_plane.core.domain import TaskRecord, TaskRequest
from mezo_control_plane.queue.consumer import ClaimedTask, TaskConsumer
from mezo_control_plane.queue.producer import QueueInfrastructureError
from mezo_control_plane.worker.execution import DurableExecutionGateway
from mezo_control_plane.worker.failure_classification import ExecutionFailure
from mezo_control_plane.worker.registration import WorkerRegistry
from mezo_control_plane.worker.runtime import WorkerRuntime


def delivery(number: int) -> ClaimedTask:
    task = TaskRecord(
        request=TaskRequest(repository="owner/repository", instruction=f"Task {number}")
    )
    return ClaimedTask(
        task=task,
        message_id=f"message-{number}",
        owner_token=f"worker:test-{number}",
        attempt=0,
        lease_expires_at=datetime.now(UTC) + timedelta(seconds=30),
    )


class FakeConsumer:
    def __init__(self, deliveries: list[ClaimedTask]) -> None:
        self.deliveries = deliveries
        self.acknowledged: list[str] = []
        self.four_acknowledged = asyncio.Event()
        self.renewal_result = True
        self.renewals = 0
        self.renewal_error = False
        self.acknowledgement_result = True

    async def claim(self, visibility_seconds: int) -> ClaimedTask | None:
        return self.deliveries.pop(0) if self.deliveries else None

    async def renew_lease(self, item: ClaimedTask, visibility_seconds: int) -> bool:
        self.renewals += 1
        if self.renewal_error:
            raise QueueInfrastructureError("redis unavailable")
        return self.renewal_result

    async def acknowledge(self, item: ClaimedTask) -> bool:
        if not self.acknowledgement_result:
            return False
        self.acknowledged.append(item.message_id)
        if len(self.acknowledged) == 4:
            self.four_acknowledged.set()
        return True


class FakeRegistry:
    def __init__(self) -> None:
        self.heartbeats: list[tuple[int, bool]] = []
        self.removed = False
        self.two_heartbeats = asyncio.Event()

    async def heartbeat(self, active_count: int, draining: bool, ttl_seconds: int = 30) -> None:
        self.heartbeats.append((active_count, draining))
        if len(self.heartbeats) >= 2:
            self.two_heartbeats.set()

    async def remove(self) -> None:
        self.removed = True


class FakePersistence:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def record_claim(self, item: ClaimedTask, worker_id: str) -> None:
        self.events.append(f"claim:{item.message_id}")

    async def record_success(self, item: ClaimedTask, output: str) -> None:
        self.events.append(f"success:{item.message_id}")

    async def record_failure(self, item: ClaimedTask, failure: ExecutionFailure) -> None:
        self.events.append(f"failure:{item.message_id}")

    async def record_interrupted(self, item: ClaimedTask, reason: str) -> None:
        self.events.append(f"interrupted:{item.message_id}")


async def test_runtime_executes_up_to_configured_concurrency() -> None:
    consumer = FakeConsumer([delivery(index) for index in range(4)])
    registry = FakeRegistry()
    persistence = FakePersistence()
    active = 0
    maximum = 0
    three_running = asyncio.Event()
    release = asyncio.Event()

    async def handler(item: ClaimedTask, cancelled: asyncio.Event) -> str:
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        if active == 3:
            three_running.set()
        await release.wait()
        active -= 1
        return item.message_id

    async def dispatch(item: ClaimedTask, failure: ExecutionFailure) -> None:
        raise AssertionError("failure dispatcher must not run")

    runtime = WorkerRuntime(
        "worker",
        cast(TaskConsumer, consumer),
        cast(WorkerRegistry, registry),
        cast(DurableExecutionGateway, persistence),
        handler,
        dispatch,
        concurrency=3,
        visibility_seconds=30,
        heartbeat_interval_seconds=0.01,
    )
    loop = asyncio.create_task(runtime.run())
    await asyncio.wait_for(three_running.wait(), timeout=1)
    assert maximum == 3
    assert len(consumer.deliveries) == 1
    release.set()
    await asyncio.wait_for(consumer.four_acknowledged.wait(), timeout=1)
    await runtime.shutdown(1)
    await loop
    assert persistence.events.index("success:message-0") < persistence.events.index(
        "success:message-3"
    )
    assert registry.removed


async def test_ownership_loss_stops_handler_without_acknowledging() -> None:
    consumer = FakeConsumer([delivery(1)])
    consumer.renewal_result = False
    registry = FakeRegistry()
    persistence = FakePersistence()
    handler_stopped = asyncio.Event()

    async def handler(item: ClaimedTask, cancelled: asyncio.Event) -> str:
        try:
            await asyncio.Event().wait()
        finally:
            handler_stopped.set()

    failures: list[ExecutionFailure] = []

    async def dispatch(item: ClaimedTask, failure: ExecutionFailure) -> None:
        failures.append(failure)

    runtime = WorkerRuntime(
        "worker",
        cast(TaskConsumer, consumer),
        cast(WorkerRegistry, registry),
        cast(DurableExecutionGateway, persistence),
        handler,
        dispatch,
        visibility_seconds=3,
        heartbeat_interval_seconds=0.01,
    )
    loop = asyncio.create_task(runtime.run())
    await asyncio.wait_for(handler_stopped.wait(), timeout=2)
    await runtime.shutdown(1)
    await loop
    assert not consumer.acknowledged
    assert failures and failures[0].classification.value == "ownership_lost"


async def test_renewal_infrastructure_failure_stops_execution() -> None:
    consumer = FakeConsumer([delivery(1)])
    consumer.renewal_error = True
    registry = FakeRegistry()
    persistence = FakePersistence()
    stopped = asyncio.Event()

    async def handler(item: ClaimedTask, cancelled: asyncio.Event) -> str:
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    failures: list[ExecutionFailure] = []

    async def dispatch(item: ClaimedTask, failure: ExecutionFailure) -> None:
        failures.append(failure)

    runtime = WorkerRuntime(
        "worker",
        cast(TaskConsumer, consumer),
        cast(WorkerRegistry, registry),
        cast(DurableExecutionGateway, persistence),
        handler,
        dispatch,
        visibility_seconds=3,
    )
    loop = asyncio.create_task(runtime.run())
    await asyncio.wait_for(stopped.wait(), timeout=2)
    await runtime.shutdown(1)
    await loop
    assert not consumer.acknowledged
    assert failures[0].classification.value == "ownership_lost"


async def test_heartbeat_runs_without_claims_and_shutdown_marks_draining() -> None:
    consumer = FakeConsumer([])
    registry = FakeRegistry()
    persistence = FakePersistence()

    async def handler(item: ClaimedTask, cancelled: asyncio.Event) -> str:
        raise AssertionError("no work should be executed")

    async def dispatch(item: ClaimedTask, failure: ExecutionFailure) -> None:
        raise AssertionError("no failure should be dispatched")

    runtime = WorkerRuntime(
        "worker",
        cast(TaskConsumer, consumer),
        cast(WorkerRegistry, registry),
        cast(DurableExecutionGateway, persistence),
        handler,
        dispatch,
        visibility_seconds=3,
        heartbeat_interval_seconds=0.001,
    )
    loop = asyncio.create_task(runtime.run())
    await asyncio.wait_for(registry.two_heartbeats.wait(), timeout=1)
    await runtime.shutdown(1)
    await loop
    assert len(registry.heartbeats) >= 2
    assert registry.heartbeats[-1][1]


async def test_durable_success_precedes_failed_redis_acknowledgement() -> None:
    consumer = FakeConsumer([delivery(1)])
    consumer.acknowledgement_result = False
    registry = FakeRegistry()
    persistence = FakePersistence()
    interrupted = asyncio.Event()

    async def handler(item: ClaimedTask, cancelled: asyncio.Event) -> str:
        return "result"

    async def dispatch(item: ClaimedTask, failure: ExecutionFailure) -> None:
        raise AssertionError("successful handler must not dispatch failure")

    original_interrupted = persistence.record_interrupted

    async def record_interrupted(item: ClaimedTask, reason: str) -> None:
        await original_interrupted(item, reason)
        interrupted.set()

    persistence.record_interrupted = record_interrupted  # type: ignore[method-assign]
    runtime = WorkerRuntime(
        "worker",
        cast(TaskConsumer, consumer),
        cast(WorkerRegistry, registry),
        cast(DurableExecutionGateway, persistence),
        handler,
        dispatch,
        visibility_seconds=3,
    )
    loop = asyncio.create_task(runtime.run())
    await asyncio.wait_for(interrupted.wait(), timeout=1)
    await runtime.shutdown(1)
    await loop
    assert persistence.events[:2] == ["claim:message-1", "success:message-1"]
    assert not consumer.acknowledged


async def test_drain_timeout_interrupts_without_acknowledging() -> None:
    consumer = FakeConsumer([delivery(1)])
    registry = FakeRegistry()
    persistence = FakePersistence()
    started = asyncio.Event()

    async def handler(item: ClaimedTask, cancelled: asyncio.Event) -> str:
        started.set()
        await asyncio.Event().wait()
        return "unreachable"

    async def dispatch(item: ClaimedTask, failure: ExecutionFailure) -> None:
        raise AssertionError("shutdown cancellation must remain recoverable")

    runtime = WorkerRuntime(
        "worker",
        cast(TaskConsumer, consumer),
        cast(WorkerRegistry, registry),
        cast(DurableExecutionGateway, persistence),
        handler,
        dispatch,
        visibility_seconds=3,
    )
    loop = asyncio.create_task(runtime.run())
    await asyncio.wait_for(started.wait(), timeout=1)
    await runtime.shutdown(0.001)
    await loop
    assert any(event.startswith("interrupted:") for event in persistence.events)
    assert not consumer.acknowledged
