from dataclasses import dataclass
from uuid import UUID

from mezo_control_plane.application.errors import ConflictError, NotFoundError
from mezo_control_plane.application.ports import HealthCheck, TaskStore
from mezo_control_plane.core.domain import EvidenceItem, TaskRecord, TaskRequest, TaskState
from mezo_control_plane.queue.cancellation import CancellationResult, CancellationService
from mezo_control_plane.queue.producer import EnqueueResult, TaskProducer


async def _configured() -> bool:
    return True


@dataclass(frozen=True)
class Page:
    items: list[TaskRecord]
    total: int
    offset: int
    limit: int


class TaskApplicationService:
    """Shared use-case layer for HTTP, Telegram, and the future dashboard."""

    def __init__(
        self,
        store: TaskStore,
        producer: TaskProducer,
        cancellation: CancellationService,
        database_health: HealthCheck,
        redis_health: HealthCheck,
        worker_health: HealthCheck,
        configuration_health: HealthCheck = _configured,
    ) -> None:
        self._store = store
        self._producer = producer
        self._cancellation = cancellation
        self._database_health = database_health
        self._redis_health = redis_health
        self._worker_health = worker_health
        self._configuration_health = configuration_health

    async def create_task(
        self, request: TaskRequest, idempotency_key: str
    ) -> tuple[TaskRecord, EnqueueResult]:
        task = await self._store.create(TaskRecord(request=request), idempotency_key)
        result = await self._producer.enqueue(task, idempotency_key)
        if result.accepted:
            task = await self._store.transition(task.id, TaskState.QUEUED)
        return task, result

    async def validate_task(self, request: TaskRequest) -> TaskRequest:
        return request

    async def get_task(self, task_id: UUID) -> TaskRecord:
        task = await self._store.get(task_id)
        if task is None:
            raise NotFoundError("Task not found")
        return task

    async def list_tasks(self, offset: int, limit: int) -> Page:
        items, total = await self._store.list_tasks(offset, limit)
        return Page(items, total, offset, limit)

    async def cancel_task(self, task_id: UUID, actor: str, reason: str) -> CancellationResult:
        task = await self.get_task(task_id)
        if task.state in {TaskState.COMPLETED, TaskState.FAILED}:
            return CancellationResult.ALREADY_TERMINAL
        await self._store.transition(task_id, TaskState.CANCELLED)
        return await self._cancellation.cancel(str(task_id), actor, reason)

    async def retry_task(self, task_id: UUID) -> TaskRecord:
        task = await self.get_task(task_id)
        if task.state not in {TaskState.FAILED, TaskState.CANCELLED}:
            raise ConflictError("Only failed or cancelled tasks can be retried")
        return await self._store.transition(task_id, TaskState.QUEUED)

    async def evidence(self, task_id: UUID) -> list[EvidenceItem]:
        await self.get_task(task_id)
        return await self._store.evidence(task_id)

    async def decide(self, task_id: UUID, approved: bool) -> TaskRecord:
        task = await self.get_task(task_id)
        expected = {TaskState.AWAITING_APPROVAL, TaskState.APPROVAL_REQUIRED}
        if task.state not in expected:
            raise ConflictError("Task is not awaiting approval")
        state = TaskState.QUEUED if approved else TaskState.CANCELLED
        return await self._store.transition(task_id, state)

    async def readiness(self) -> dict[str, bool]:
        return {
            "postgresql": await self._database_health(),
            "redis": await self._redis_health(),
            "workers": await self._worker_health(),
            "configuration": await self._configuration_health(),
        }
