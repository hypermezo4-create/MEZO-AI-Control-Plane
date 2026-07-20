from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mezo_control_plane.core.domain import AuditEvent, EvidenceItem, TaskRecord, TaskState
from mezo_control_plane.database.base import AuditEventRow, EvidenceRow, TaskAttemptRow, TaskRow


class TaskRepository:
    """Transactional persistence boundary for task records and immutable evidence."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        return self._sessions

    async def create(self, task: TaskRecord, idempotency_key: str) -> TaskRecord:
        async with self._sessions.begin() as session:
            inserted = await session.scalar(
                pg_insert(TaskRow)
                .values(
                    id=task.id,
                    idempotency_key=idempotency_key,
                    repository=task.request.repository,
                    instruction=task.request.instruction,
                    state=task.state.value,
                    risk=task.risk.value,
                    created_at=task.created_at,
                    updated_at=task.updated_at,
                )
                .on_conflict_do_nothing(index_elements=[TaskRow.idempotency_key])
                .returning(TaskRow.id)
            )
            if inserted is None:
                existing = await session.scalar(
                    select(TaskRow).where(TaskRow.idempotency_key == idempotency_key)
                )
                if existing is None:
                    raise RuntimeError("Idempotent task insert could not be reconciled")
                return self._to_record(existing)
        return task

    async def append_evidence(self, task_id: UUID, item: EvidenceItem) -> None:
        if item.immutable_hash is None:
            raise ValueError("Evidence requires an immutable hash")
        async with self._sessions.begin() as session:
            session.add(
                EvidenceRow(
                    id=uuid4(),
                    task_id=task_id,
                    kind=item.kind,
                    summary=item.summary,
                    immutable_hash=item.immutable_hash,
                    created_at=item.created_at,
                )
            )

    async def append_audit_event(self, task_id: UUID, event: AuditEvent) -> None:
        async with self._sessions.begin() as session:
            session.add(
                AuditEventRow(
                    id=uuid4(),
                    task_id=task_id,
                    action=event.action,
                    actor=event.actor,
                    idempotency_key=event.idempotency_key,
                    detail=event.detail,
                    occurred_at=event.occurred_at,
                )
            )

    async def get(self, task_id: UUID) -> TaskRecord | None:
        async with self._sessions() as session:
            row = await session.scalar(select(TaskRow).where(TaskRow.id == task_id))
            return self._to_record(row) if row else None

    async def list_tasks(self, offset: int = 0, limit: int = 50) -> tuple[list[TaskRecord], int]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(TaskRow)
                .order_by(TaskRow.created_at.desc(), TaskRow.id)
                .offset(offset)
                .limit(limit)
            )
            total = await session.scalar(select(func.count()).select_from(TaskRow))
            return [self._to_record(row) for row in rows], int(total or 0)

    async def transition(self, task_id: UUID, state: TaskState) -> TaskRecord:
        async with self._sessions.begin() as session:
            row = await session.scalar(
                select(TaskRow).where(TaskRow.id == task_id).with_for_update()
            )
            if row is None:
                raise LookupError("Task not found")
            row.state = state.value
            row.updated_at = datetime.now(UTC)
        record = await self.get(task_id)
        if record is None:
            raise LookupError("Task not found after transition")
        return record

    async def evidence(self, task_id: UUID) -> list[EvidenceItem]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(EvidenceRow)
                .where(EvidenceRow.task_id == task_id)
                .order_by(EvidenceRow.created_at, EvidenceRow.id)
            )
            return [
                EvidenceItem(
                    kind=row.kind,
                    summary=row.summary,
                    immutable_hash=row.immutable_hash,
                    created_at=row.created_at,
                )
                for row in rows
            ]

    async def stream_stale_attempts(self, before: datetime) -> AsyncIterator[UUID]:
        async with self._sessions() as session:
            result = await session.scalars(
                select(TaskAttemptRow.id).where(TaskAttemptRow.lease_expires_at < before)
            )
            for attempt_id in result:
                yield attempt_id

    @staticmethod
    def _to_record(row: TaskRow) -> TaskRecord:
        from mezo_control_plane.core.domain import RiskLevel, TaskRequest, TaskState

        return TaskRecord(
            id=row.id,
            request=TaskRequest(repository=row.repository, instruction=row.instruction),
            state=TaskState(row.state),
            risk=RiskLevel(row.risk),
            created_at=row.created_at.replace(tzinfo=UTC),
            updated_at=row.updated_at.replace(tzinfo=UTC),
        )
