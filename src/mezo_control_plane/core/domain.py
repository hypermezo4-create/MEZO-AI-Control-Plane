from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class TaskState(StrEnum):
    RECEIVED = "received"
    CONTEXT_READY = "context_ready"
    PLANNED = "planned"
    APPROVAL_REQUIRED = "approval_required"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    REVIEWING = "reviewing"
    READY_FOR_PR = "ready_for_pr"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TaskRequest(BaseModel):
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    instruction: str = Field(min_length=3, max_length=20_000)
    base_branch: str = "main"
    dry_run: bool = True


class TaskRecord(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    request: TaskRequest
    state: TaskState = TaskState.RECEIVED
    risk: RiskLevel = RiskLevel.MEDIUM
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    evidence: list[str] = Field(default_factory=list)
    failure_reason: str | None = None


class ModelMessage(BaseModel):
    role: str
    content: str


class ModelRequest(BaseModel):
    messages: list[ModelMessage]
    system_instruction: str | None = None
    temperature: float = Field(default=0.1, ge=0, le=2)
    max_output_tokens: int = Field(default=8192, ge=64, le=65_536)


class ModelResponse(BaseModel):
    provider: str
    model: str
    text: str
    request_id: str | None = None
