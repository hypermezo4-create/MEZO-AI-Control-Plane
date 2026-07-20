import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol

from mezo_control_plane.queue.consumer import ClaimedTask
from mezo_control_plane.worker.failure_classification import ExecutionFailure


class DurableExecutionGateway(Protocol):
    async def record_claim(self, delivery: ClaimedTask, worker_id: str) -> None: ...

    async def record_success(self, delivery: ClaimedTask, output: str) -> None: ...

    async def record_failure(self, delivery: ClaimedTask, failure: ExecutionFailure) -> None: ...

    async def record_interrupted(self, delivery: ClaimedTask, reason: str) -> None: ...


ExecutionHandler = Callable[[ClaimedTask, asyncio.Event], Awaitable[str]]
