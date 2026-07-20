from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentRole(StrEnum):
    PLANNER = "planner"
    EXECUTOR = "executor"
    BLIND_REVIEWER = "blind_reviewer"
    SECURITY_REVIEWER = "security_reviewer"
    FINAL_VERIFIER = "final_verifier"


class DeliveryDecision(StrEnum):
    ACCEPT = "accept"
    CORRECT = "correct"
    BLOCK = "block"


class AgentLimits(BaseModel):
    max_tokens: int = Field(ge=64, le=65_536)
    max_model_calls: int = Field(ge=1, le=20)
    max_tool_calls: int = Field(ge=0, le=200)
    max_corrective_rounds: int = Field(ge=0, le=10)
    deadline_seconds: float = Field(gt=0, le=3600)


class ContextReference(BaseModel):
    citation_id: str = Field(min_length=1, max_length=128)
    path: str = Field(min_length=1, max_length=1024)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class PlannerInput(BaseModel):
    original_instruction: str = Field(min_length=3, max_length=20_000)
    repository: str
    base_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    repository_rules: tuple[str, ...]
    context: tuple[ContextReference, ...]
    risk_policy: str
    available_tools: tuple[str, ...]
    required_skills: tuple[str, ...]
    task_budget: AgentLimits


class PlannerOutput(BaseModel):
    problem_statement: str
    root_cause_hypotheses: tuple[str, ...]
    assumptions: tuple[str, ...]
    likely_files: tuple[str, ...]
    investigation_steps: tuple[str, ...]
    implementation_steps: tuple[str, ...]
    tests: tuple[str, ...]
    risks: tuple[str, ...]
    approval_requirements: tuple[str, ...]
    expected_evidence: tuple[str, ...]
    stop_conditions: tuple[str, ...]


class ToolProposal(BaseModel):
    tool_name: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any]
    context_citations: tuple[str, ...]
    rationale: str = Field(min_length=1, max_length=2000)


class ExecutorInput(BaseModel):
    approved_plan: PlannerOutput
    approved_context: tuple[ContextReference, ...]
    remaining_tool_calls: int = Field(ge=0)
    approval_boundaries: tuple[str, ...] = ()


class ExecutorOutput(BaseModel):
    proposals: tuple[ToolProposal, ...]
    checkpoint: str
    stopped_for_approval: bool = False
    completed_scope: tuple[str, ...] = ()


class ReviewFinding(BaseModel):
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    severity: str = Field(pattern=r"^(critical|important|advisory)$")
    path: str
    evidence: str
    reproduction: tuple[str, ...] = ()
    correction: str


class BlindReviewInput(BaseModel):
    original_task: str
    repository_rules: tuple[str, ...]
    approved_plan: PlannerOutput
    base_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    diff: str
    changed_files: tuple[str, ...]
    test_evidence: tuple[str, ...]
    guard_receipts: tuple[str, ...]
    risk_decisions: tuple[str, ...]
    tool_evidence: tuple[str, ...]


class ReviewOutput(BaseModel):
    findings: tuple[ReviewFinding, ...]
    decision: DeliveryDecision


class SecurityReviewInput(BaseModel):
    diff: str
    changed_files: tuple[str, ...]
    trust_boundaries: tuple[str, ...]
    permissions: tuple[str, ...]
    network_policy: str
    filesystem_policy: str


class FinalVerifierInput(BaseModel):
    acceptance_criteria: tuple[str, ...]
    completed_plan_steps: tuple[str, ...]
    diff_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    test_evidence: tuple[str, ...]
    guard_receipts: tuple[str, ...]
    review_findings: tuple[ReviewFinding, ...]
    approvals: tuple[str, ...]
    repository_head: str = Field(pattern=r"^[0-9a-f]{40}$")
    expected_base: str = Field(pattern=r"^[0-9a-f]{40}$")
    evidence_created_at: datetime
    verification_time: datetime = Field(default_factory=lambda: datetime.now(UTC))


class FinalVerifierOutput(BaseModel):
    ready: bool
    missing_evidence: tuple[str, ...]
    stale_evidence: tuple[str, ...]
    reasons: tuple[str, ...]


class AgentFailure(BaseModel):
    code: str
    summary: str
    retryable: bool
    evidence: tuple[str, ...] = ()


class AgentExecutionRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    invocation_id: str
    task_id: str
    role: AgentRole
    prompt_version: str
    provider: str
    model: str
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_calls: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    started_at: datetime
    completed_at: datetime
    failure: AgentFailure | None = None
