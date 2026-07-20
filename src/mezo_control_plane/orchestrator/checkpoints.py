from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol


@dataclass(frozen=True)
class WorkflowCheckpoint:
    task_id: str
    stage: str
    sequence: int
    input_hash: str
    output_hash: str
    prompt_version: str | None
    provider_evidence: tuple[str, ...]
    tool_evidence: tuple[str, ...]
    created_at: datetime


class CheckpointStore(Protocol):
    async def append(self, checkpoint: WorkflowCheckpoint) -> WorkflowCheckpoint: ...
    async def latest(self, task_id: str) -> WorkflowCheckpoint | None: ...
    async def list(self, task_id: str) -> tuple[WorkflowCheckpoint, ...]: ...


class InMemoryCheckpointStore:
    def __init__(self) -> None:
        self._items: dict[str, list[WorkflowCheckpoint]] = {}
        self._lock = asyncio.Lock()

    async def append(self, checkpoint: WorkflowCheckpoint) -> WorkflowCheckpoint:
        async with self._lock:
            items = self._items.setdefault(checkpoint.task_id, [])
            if any(
                item.stage == checkpoint.stage and item.input_hash == checkpoint.input_hash
                for item in items
            ):
                return next(
                    item
                    for item in items
                    if item.stage == checkpoint.stage and item.input_hash == checkpoint.input_hash
                )
            if checkpoint.sequence != len(items) + 1:
                raise ValueError("Checkpoint sequence is not contiguous")
            items.append(checkpoint)
            return checkpoint

    async def latest(self, task_id: str) -> WorkflowCheckpoint | None:
        items = self._items.get(task_id, [])
        return items[-1] if items else None

    async def list(self, task_id: str) -> tuple[WorkflowCheckpoint, ...]:
        return tuple(self._items.get(task_id, ()))


def new_checkpoint(
    task_id: str,
    stage: str,
    sequence: int,
    input_hash: str,
    output_hash: str,
    *,
    prompt_version: str | None = None,
    provider_evidence: tuple[str, ...] = (),
    tool_evidence: tuple[str, ...] = (),
) -> WorkflowCheckpoint:
    return WorkflowCheckpoint(
        task_id,
        stage,
        sequence,
        input_hash,
        output_hash,
        prompt_version,
        provider_evidence,
        tool_evidence,
        datetime.now(UTC),
    )

