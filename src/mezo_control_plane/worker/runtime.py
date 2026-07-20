import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

from mezo_control_plane.queue.cancellation import CancellationService
from mezo_control_plane.queue.consumer import ClaimedTask, TaskConsumer
from mezo_control_plane.queue.producer import QueueInfrastructureError
from mezo_control_plane.worker.execution import DurableExecutionGateway, ExecutionHandler
from mezo_control_plane.worker.failure_classification import (
    ExecutionFailure,
    FailureClass,
    classify_failure,
)
from mezo_control_plane.worker.registration import WorkerRegistry

MaintenanceOperation = Callable[[], Awaitable[object]]
FailureDispatcher = Callable[[ClaimedTask, ExecutionFailure], Awaitable[None]]


class WorkerRuntime:
    def __init__(
        self,
        worker_id: str,
        consumer: TaskConsumer,
        registry: WorkerRegistry,
        persistence: DurableExecutionGateway,
        handler: ExecutionHandler,
        failure_dispatcher: FailureDispatcher,
        *,
        concurrency: int = 2,
        visibility_seconds: int = 60,
        execution_timeout_seconds: float = 900,
        heartbeat_interval_seconds: float = 10,
        maintenance_interval_seconds: float = 1,
        maintenance: tuple[MaintenanceOperation, ...] = (),
        cancellation_service: CancellationService | None = None,
    ) -> None:
        if concurrency < 1 or visibility_seconds < 3:
            raise ValueError("Worker concurrency and visibility timeout must be positive")
        self._worker_id = worker_id
        self._consumer = consumer
        self._registry = registry
        self._persistence = persistence
        self._handler = handler
        self._failure_dispatcher = failure_dispatcher
        self._capacity = concurrency
        self._visibility_seconds = visibility_seconds
        self._execution_timeout = execution_timeout_seconds
        self._heartbeat_interval = heartbeat_interval_seconds
        self._maintenance_interval = maintenance_interval_seconds
        self._maintenance = maintenance
        self._cancellation_service = cancellation_service
        self._active: dict[str, asyncio.Task[None]] = {}
        self._draining = asyncio.Event()
        self._stopped = asyncio.Event()
        self._background: set[asyncio.Task[None]] = set()
        self._background_failures = 0

    @property
    def active_count(self) -> int:
        return len(self._active)

    async def run(self) -> None:
        self._spawn_background(self._heartbeat_loop())
        self._spawn_background(self._maintenance_loop())
        try:
            while not self._draining.is_set():
                self._prune_finished()
                if len(self._active) >= self._capacity:
                    await asyncio.sleep(0)
                    continue
                try:
                    delivery = await self._consumer.claim(self._visibility_seconds)
                except QueueInfrastructureError:
                    await asyncio.sleep(self._maintenance_interval)
                    continue
                if delivery is None:
                    await asyncio.sleep(0.01)
                    continue
                task = asyncio.create_task(self._execute(delivery))
                self._active[delivery.message_id] = task
        finally:
            self._stopped.set()

    async def shutdown(self, drain_timeout_seconds: float) -> None:
        self._draining.set()
        await self._registry.heartbeat(self.active_count, True)
        try:
            async with asyncio.timeout(drain_timeout_seconds):
                if self._active:
                    await asyncio.gather(*self._active.values(), return_exceptions=True)
        except TimeoutError:
            for task in self._active.values():
                task.cancel()
            if self._active:
                await asyncio.gather(*self._active.values(), return_exceptions=True)
        self._stopped.set()
        for task in self._background:
            task.cancel()
        if self._background:
            await asyncio.gather(*self._background, return_exceptions=True)
        await self._registry.remove()

    async def _execute(self, delivery: ClaimedTask) -> None:
        cancellation = asyncio.Event()
        ownership_lost = asyncio.Event()
        renewal = asyncio.create_task(self._renewal_loop(delivery, cancellation, ownership_lost))
        handler_task: asyncio.Future[str] | None = None
        try:
            if self._cancellation_service is not None:
                self._cancellation_service.register_running(str(delivery.task.id), cancellation)
            await self._persistence.record_claim(delivery, self._worker_id)
            handler_task = asyncio.ensure_future(self._handler(delivery, cancellation))
            ownership_waiter = asyncio.create_task(ownership_lost.wait())
            async with asyncio.timeout(self._execution_timeout):
                done, _ = await asyncio.wait(
                    {handler_task, ownership_waiter}, return_when=asyncio.FIRST_COMPLETED
                )
                if ownership_waiter in done and ownership_lost.is_set():
                    handler_task.cancel()
                    await asyncio.gather(handler_task, return_exceptions=True)
                    raise RuntimeError("lease ownership lost")
                ownership_waiter.cancel()
                await asyncio.gather(ownership_waiter, return_exceptions=True)
                output = await handler_task
            if ownership_lost.is_set() or cancellation.is_set():
                raise asyncio.CancelledError
            await self._persistence.record_success(delivery, output)
            acknowledged = await self._consumer.acknowledge(delivery)
            if not acknowledged:
                await self._persistence.record_interrupted(delivery, "redis-acknowledgement-failed")
        except asyncio.CancelledError:
            await self._persistence.record_interrupted(delivery, "cancelled-or-ownership-lost")
            raise
        except BaseException as error:
            failure = classify_failure(error)
            if ownership_lost.is_set():
                failure = ExecutionFailure(
                    FailureClass.OWNERSHIP_LOST, "lease ownership lost", True
                )
            await self._persistence.record_failure(delivery, failure)
            await self._failure_dispatcher(delivery, failure)
        finally:
            if self._cancellation_service is not None:
                self._cancellation_service.unregister_running(str(delivery.task.id))
            cancellation.set()
            if handler_task is not None and not handler_task.done():
                handler_task.cancel()
                await asyncio.gather(handler_task, return_exceptions=True)
            renewal.cancel()
            await asyncio.gather(renewal, return_exceptions=True)

    async def _renewal_loop(
        self,
        delivery: ClaimedTask,
        cancellation: asyncio.Event,
        ownership_lost: asyncio.Event,
    ) -> None:
        interval = self._visibility_seconds / 3
        while not cancellation.is_set():
            await asyncio.sleep(interval)
            if not await self._consumer.renew_lease(delivery, self._visibility_seconds):
                ownership_lost.set()
                cancellation.set()
                return

    async def _heartbeat_loop(self) -> None:
        while not self._stopped.is_set():
            try:
                await self._registry.heartbeat(self.active_count, self._draining.is_set())
            except QueueInfrastructureError:
                self._background_failures += 1
            await asyncio.sleep(self._heartbeat_interval)

    async def _maintenance_loop(self) -> None:
        while not self._stopped.is_set():
            for operation in self._maintenance:
                try:
                    await operation()
                except QueueInfrastructureError:
                    self._background_failures += 1
                    continue
            await asyncio.sleep(self._maintenance_interval)

    def _spawn_background(self, coroutine: Coroutine[Any, Any, None]) -> None:
        task: asyncio.Task[None] = asyncio.create_task(coroutine)
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    def _prune_finished(self) -> None:
        finished = [message_id for message_id, task in self._active.items() if task.done()]
        for message_id in finished:
            self._active.pop(message_id)
