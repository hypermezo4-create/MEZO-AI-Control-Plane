from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from mezo_control_plane.database.base import Base


class WorkflowCheckpointRow(Base):
    __tablename__ = "workflow_checkpoints"
    __table_args__ = (
        UniqueConstraint("task_id", "sequence", name="uq_workflow_checkpoint_sequence"),
        UniqueConstraint("task_id", "stage", "input_hash", name="uq_workflow_stage_input"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    task_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    stage: Mapped[str] = mapped_column(String(64), index=True)
    input_hash: Mapped[str] = mapped_column(String(64))
    output_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class AgentInvocationRow(Base):
    __tablename__ = "agent_invocations"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    task_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    role: Mapped[str] = mapped_column(String(64), index=True)
    prompt_version: Mapped[str] = mapped_column(String(64))
    input_hash: Mapped[str] = mapped_column(String(64))
    output_hash: Mapped[str] = mapped_column(String(64))
    evidence: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class PromptVersionRow(Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (UniqueConstraint("role", "version", name="uq_prompt_role_version"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    role: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ModelAttemptRow(Base):
    __tablename__ = "model_attempts"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    invocation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    provider: Mapped[str] = mapped_column(String(128))
    model: Mapped[str] = mapped_column(String(255))
    outcome: Mapped[str] = mapped_column(String(40))
    evidence: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ToolCallRecordRow(Base):
    __tablename__ = "tool_call_records"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    task_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    input_hash: Mapped[str] = mapped_column(String(64))
    output_hash: Mapped[str] = mapped_column(String(64))
    evidence: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class SandboxRecordRow(Base):
    __tablename__ = "sandbox_records"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    task_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    state: Mapped[str] = mapped_column(String(40), index=True)
    base_sha: Mapped[str] = mapped_column(String(40))
    policy: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class RepositoryAnalysisRow(Base):
    __tablename__ = "repository_analyses"
    __table_args__ = (
        UniqueConstraint(
            "repository", "commit_sha", "configuration_hash", name="uq_repository_analysis_cache"
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    repository: Mapped[str] = mapped_column(String(255), index=True)
    commit_sha: Mapped[str] = mapped_column(String(40))
    configuration_hash: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ContextCitationRow(Base):
    __tablename__ = "context_citations"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    analysis_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    path: Mapped[str] = mapped_column(Text)
    line_start: Mapped[int] = mapped_column(Integer)
    line_end: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class GitHubInstallationReferenceRow(Base):
    __tablename__ = "github_installation_references"
    __table_args__ = (
        UniqueConstraint("installation_id", "repository", name="uq_installation_repository"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    installation_id: Mapped[int] = mapped_column(Integer)
    repository: Mapped[str] = mapped_column(String(255))
    permissions: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class BranchDeliveryRow(Base):
    __tablename__ = "branch_deliveries"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    task_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), unique=True)
    repository: Mapped[str] = mapped_column(String(255))
    branch: Mapped[str] = mapped_column(String(255))
    base_sha: Mapped[str] = mapped_column(String(40))
    head_sha: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ReviewFindingRow(Base):
    __tablename__ = "review_findings"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    task_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(20))
    evidence: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class GuardReceiptRecordRow(Base):
    __tablename__ = "guard_receipt_records"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    task_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    skill: Mapped[str] = mapped_column(String(128))
    receipt_hash: Mapped[str] = mapped_column(String(64), unique=True)
    receipt: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class PolicyDecisionRow(Base):
    __tablename__ = "policy_decision_records"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    task_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    decision_hash: Mapped[str] = mapped_column(String(64), unique=True)
    decision: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ApprovalRecordRow(Base):
    __tablename__ = "approval_records"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    task_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    approval_id: Mapped[str] = mapped_column(String(128), unique=True)
    record: Mapped[dict[str, object]] = mapped_column(JSON)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class DraftPullRequestDeliveryRow(Base):
    __tablename__ = "draft_pr_deliveries"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    task_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), unique=True)
    repository: Mapped[str] = mapped_column(String(255))
    pull_number: Mapped[int | None] = mapped_column(Integer)
    payload_hash: Mapped[str] = mapped_column(String(64), unique=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
