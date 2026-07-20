from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class TaskState(StrEnum):
    RECEIVED = "received"
    VALIDATED = "validated"
    AWAITING_APPROVAL = "awaiting_approval"
    QUEUED = "queued"
    PLANNING = "planning"
    EXECUTING = "executing"
    TESTING = "testing"
    GUARDING = "guarding"
    REVIEWING = "reviewing"
    FIXING = "fixing"
    READY_FOR_PR = "ready_for_pr"
    PR_OPENED = "pr_opened"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    # Compatibility states retained while callers migrate to the explicit lifecycle.
    CONTEXT_READY = "context_ready"
    PLANNED = "planned"
    APPROVAL_REQUIRED = "approval_required"
    VERIFYING = "verifying"


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


class RepositoryTarget(BaseModel):
    full_name: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    base_branch: str = Field(default="main", min_length=1, max_length=255)
    base_sha: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")


class EvidenceItem(BaseModel):
    kind: str = Field(min_length=1, max_length=64)
    summary: str = Field(min_length=1, max_length=4_000)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    immutable_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class AuditEvent(BaseModel):
    action: str = Field(min_length=1, max_length=128)
    actor: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=255)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    detail: str = Field(default="", max_length=4_000)


class TaskAttempt(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    number: int = Field(ge=1)
    state: TaskState = TaskState.QUEUED
    lease_expires_at: datetime | None = None


class Execution(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    attempt_id: UUID
    sandbox_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class Plan(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    steps: list[str] = Field(min_length=1, max_length=100)
    risk_summary: str = Field(min_length=1, max_length=4_000)


class Patch(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    unified_diff: str = Field(min_length=1, max_length=2_000_000)
    changed_paths: list[str] = Field(default_factory=list, max_length=1_000)


class ToolCall(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=128)
    arguments: dict[str, object] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1, max_length=255)


class Approval(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    approved: bool
    actor: str = Field(min_length=1, max_length=128)
    reason: str = Field(default="", max_length=4_000)


class Review(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    reviewer_role: str = Field(min_length=1, max_length=64)
    approved: bool
    findings: list[str] = Field(default_factory=list, max_length=100)


class GuardReceipt(BaseModel):
    skill: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)
    commit: str = Field(min_length=7, max_length=64)
    result: str = Field(pattern=r"^(pass|changes-required)$")
    findings: list[dict[str, str]] = Field(default_factory=list, max_length=100)


class ModelUsage(BaseModel):
    provider: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=256)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0)


class DeploymentRequest(BaseModel):
    task_id: UUID
    environment: str = Field(min_length=1, max_length=64)
    approved_by: str | None = Field(default=None, max_length=128)


class TaskRecord(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    request: TaskRequest
    state: TaskState = TaskState.RECEIVED
    risk: RiskLevel = RiskLevel.MEDIUM
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    evidence: list[str] = Field(default_factory=list)
    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    audit_events: list[AuditEvent] = Field(default_factory=list)
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
