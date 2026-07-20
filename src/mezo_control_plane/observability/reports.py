from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from mezo_control_plane.core.domain import EvidenceItem, TaskRecord


class TaskReport(BaseModel):
    task: TaskRecord
    evidence: list[EvidenceItem]
    evidence_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def build_task_report(task: TaskRecord, evidence: list[EvidenceItem]) -> TaskReport:
    canonical = [item.model_dump(mode="json") for item in evidence]
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return TaskReport(task=task, evidence=evidence, evidence_digest=digest)
