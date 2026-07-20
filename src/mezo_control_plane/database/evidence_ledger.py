from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mezo_control_plane.database.control_records import EvidenceLedgerRow
from mezo_control_plane.observability.evidence import EvidenceLedger, LedgerEntry


class EvidenceLedgerRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def entries(self, task_id: UUID) -> tuple[LedgerEntry, ...]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(EvidenceLedgerRow)
                .where(EvidenceLedgerRow.task_id == task_id)
                .order_by(EvidenceLedgerRow.sequence)
            )
            return tuple(self._to_entry(row) for row in rows)

    async def verify(self, task_id: UUID) -> bool:
        try:
            EvidenceLedger(await self.entries(task_id))
        except ValueError:
            return False
        return True

    @staticmethod
    def _to_entry(row: EvidenceLedgerRow) -> LedgerEntry:
        return LedgerEntry(
            task_id=row.task_id,
            sequence=row.sequence,
            kind=row.kind,
            summary=row.summary,
            payload=row.payload,
            previous_hash=row.previous_hash,
            entry_hash=row.entry_hash,
            created_at=row.created_at,
        )
