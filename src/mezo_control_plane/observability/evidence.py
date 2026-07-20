from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, Field


class LedgerEntry(BaseModel):
    task_id: UUID
    sequence: int = Field(ge=1)
    kind: str = Field(min_length=1, max_length=64)
    summary: str = Field(min_length=1, max_length=4_000)
    payload: dict[str, object] = Field(default_factory=dict)
    previous_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    entry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class EvidenceLedger:
    """Append-only, hash-chained evidence ledger used by durable adapters."""

    def __init__(self, entries: tuple[LedgerEntry, ...] = ()) -> None:
        self._entries = list(entries)
        if not self.verify():
            raise ValueError("Invalid evidence ledger chain")

    @property
    def entries(self) -> tuple[LedgerEntry, ...]:
        return tuple(self._entries)

    def append(
        self,
        task_id: UUID,
        kind: str,
        summary: str,
        payload: dict[str, object] | None = None,
        created_at: datetime | None = None,
    ) -> LedgerEntry:
        if self._entries and self._entries[0].task_id != task_id:
            raise ValueError("Evidence ledger cannot mix task identifiers")
        previous_hash = self._entries[-1].entry_hash if self._entries else "0" * 64
        sequence = len(self._entries) + 1
        timestamp = created_at or datetime.now(UTC)
        entry_hash = compute_entry_hash(
            task_id=task_id,
            sequence=sequence,
            kind=kind,
            summary=summary,
            payload=payload or {},
            previous_hash=previous_hash,
            created_at=timestamp,
        )
        entry = LedgerEntry(
            task_id=task_id,
            sequence=sequence,
            kind=kind,
            summary=summary,
            payload=payload or {},
            previous_hash=previous_hash,
            entry_hash=entry_hash,
            created_at=timestamp,
        )
        self._entries.append(entry)
        return entry

    def verify(self) -> bool:
        previous_hash = "0" * 64
        expected_task_id = self._entries[0].task_id if self._entries else None
        for expected_sequence, entry in enumerate(self._entries, start=1):
            if entry.task_id != expected_task_id:
                return False
            if entry.sequence != expected_sequence or entry.previous_hash != previous_hash:
                return False
            expected_hash = compute_entry_hash(
                task_id=entry.task_id,
                sequence=entry.sequence,
                kind=entry.kind,
                summary=entry.summary,
                payload=entry.payload,
                previous_hash=entry.previous_hash,
                created_at=entry.created_at,
            )
            if entry.entry_hash != expected_hash:
                return False
            previous_hash = entry.entry_hash
        return True


def compute_entry_hash(
    *,
    task_id: UUID,
    sequence: int,
    kind: str,
    summary: str,
    payload: dict[str, object],
    previous_hash: str,
    created_at: datetime,
) -> str:
    document = {
        "created_at": created_at.astimezone(UTC).isoformat(),
        "kind": kind,
        "payload": payload,
        "previous_hash": previous_hash,
        "sequence": sequence,
        "summary": summary,
        "task_id": str(task_id),
    }
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()
