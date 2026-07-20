import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mezo_control_plane.core.domain import TaskState
from mezo_control_plane.database.base import EvidenceRow, TaskAttemptRow, TaskRow
from mezo_control_plane.queue.consumer import ClaimedTask
from mezo_control_plane.worker.failure_classification import ExecutionFailure


class DurableTaskTerminalError(Exception):
    pass


class SqlAlchemyExecutionGateway:
    """Commits durable decisions before callers mutate Redis delivery state."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def record_claim(self, delivery: ClaimedTask, worker_id: str) -> None:
        async with self._sessions.begin() as session:
            task = await self._task_for_update(session, delivery.task.id)
            if task.state in {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}:
                raise DurableTaskTerminalError(f"Task is already {task.state}")
            existing = await session.scalar(
                select(TaskAttemptRow).where(
                    TaskAttemptRow.task_id == delivery.task.id,
                    TaskAttemptRow.number == delivery.attempt + 1,
                )
            )
            if existing is None:
                session.add(
                    TaskAttemptRow(
                        id=uuid4(),
                        task_id=delivery.task.id,
                        number=delivery.attempt + 1,
                        state=TaskState.EXECUTING.value,
                        lease_owner=worker_id,
                        lease_expires_at=delivery.lease_expires_at,
                    )
                )
            task.state = TaskState.EXECUTING.value
            task.updated_at = datetime.now(UTC)
            self._add_evidence(
                session,
                delivery.task.id,
                "queue-claim",
                f"message={delivery.message_id};worker={worker_id};attempt={delivery.attempt + 1}",
            )

    async def record_success(self, delivery: ClaimedTask, output: str) -> None:
        async with self._sessions.begin() as session:
            task = await self._task_for_update(session, delivery.task.id)
            if task.state == TaskState.CANCELLED:
                raise DurableTaskTerminalError("Cancelled task cannot be completed")
            self._add_evidence(session, delivery.task.id, "execution-result", output)
            task.state = TaskState.COMPLETED.value
            task.updated_at = datetime.now(UTC)

    async def record_failure(self, delivery: ClaimedTask, failure: ExecutionFailure) -> None:
        async with self._sessions.begin() as session:
            task = await self._task_for_update(session, delivery.task.id)
            self._add_evidence(
                session,
                delivery.task.id,
                "execution-failure",
                f"{failure.classification.value}:{failure.summary}",
            )
            task.state = TaskState.QUEUED.value if failure.retryable else TaskState.FAILED.value
            task.updated_at = datetime.now(UTC)

    async def record_interrupted(self, delivery: ClaimedTask, reason: str) -> None:
        async with self._sessions.begin() as session:
            task = await self._task_for_update(session, delivery.task.id)
            self._add_evidence(session, delivery.task.id, "execution-interrupted", reason)
            if task.state not in {
                TaskState.COMPLETED,
                TaskState.FAILED,
                TaskState.CANCELLED,
            }:
                task.state = TaskState.QUEUED.value
            task.updated_at = datetime.now(UTC)

    async def record_recovery(
        self, task_id: UUID, previous_worker: str | None, reason: str
    ) -> TaskState:
        async with self._sessions.begin() as session:
            task = await self._task_for_update(session, task_id)
            self._add_evidence(
                session,
                task_id,
                "lease-recovery",
                f"previous_worker={previous_worker or 'unknown'};reason={reason}",
            )
            return TaskState(task.state)

    async def state(self, task_id: str) -> str | None:
        try:
            parsed = UUID(task_id)
        except ValueError:
            return None
        async with self._sessions() as session:
            state: str | None = await session.scalar(
                select(TaskRow.state).where(TaskRow.id == parsed)
            )
            return state

    @staticmethod
    async def _task_for_update(session: AsyncSession, task_id: UUID) -> TaskRow:
        task = await session.scalar(select(TaskRow).where(TaskRow.id == task_id).with_for_update())
        if task is None:
            raise LookupError("Durable task does not exist")
        return task

    @staticmethod
    def _add_evidence(session: AsyncSession, task_id: UUID, kind: str, summary: str) -> None:
        canonical = json.dumps(
            {"kind": kind, "summary": summary, "task_id": str(task_id)},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()
        session.add(
            EvidenceRow(
                id=uuid4(),
                task_id=task_id,
                kind=kind,
                summary=summary,
                immutable_hash=hashlib.sha256(canonical).hexdigest(),
                created_at=datetime.now(UTC),
            )
        )
