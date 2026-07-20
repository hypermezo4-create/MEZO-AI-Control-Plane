from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mezo_control_plane.core.domain import EvidenceItem
from mezo_control_plane.database.base import EvidenceRow
from mezo_control_plane.database.control_records import EvidenceLedgerRow
from mezo_control_plane.observability.evidence import compute_entry_hash


async def append_evidence_records(
    session: AsyncSession,
    task_id: UUID,
    item: EvidenceItem,
) -> None:
    """Append the compatibility evidence row and ledger entry in one transaction."""
    if item.immutable_hash is None:
        raise ValueError("Evidence requires an immutable hash")
    previous = await session.scalar(
        select(EvidenceLedgerRow)
        .where(EvidenceLedgerRow.task_id == task_id)
        .order_by(EvidenceLedgerRow.sequence.desc())
        .limit(1)
    )
    sequence = previous.sequence + 1 if previous is not None else 1
    previous_hash = previous.entry_hash if previous is not None else "0" * 64
    payload: dict[str, object] = {"immutable_hash": item.immutable_hash}
    entry_hash = compute_entry_hash(
        task_id=task_id,
        sequence=sequence,
        kind=item.kind,
        summary=item.summary,
        payload=payload,
        previous_hash=previous_hash,
        created_at=item.created_at,
    )
    session.add_all(
        [
            EvidenceRow(
                id=uuid4(),
                task_id=task_id,
                kind=item.kind,
                summary=item.summary,
                immutable_hash=item.immutable_hash,
                created_at=item.created_at,
            ),
            EvidenceLedgerRow(
                id=uuid4(),
                task_id=task_id,
                sequence=sequence,
                kind=item.kind,
                summary=item.summary,
                payload=payload,
                previous_hash=previous_hash,
                entry_hash=entry_hash,
                created_at=item.created_at,
            ),
        ]
    )
