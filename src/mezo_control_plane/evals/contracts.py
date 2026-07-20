from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class EvalCategory(StrEnum):
    ROOT_CAUSE = "root_cause"
    HALLUCINATED_API = "hallucinated_api"
    TOOL_SCHEMA = "tool_schema"
    PROMPT_INJECTION = "prompt_injection"
    REVIEWER_INDEPENDENCE = "reviewer_independence"
    LOOP_TERMINATION = "loop_termination"
    TEST_TRUTHFULNESS = "test_truthfulness"
    PROTECTED_BRANCH = "protected_branch"
    APPROVAL_BOUNDARY = "approval_boundary"


class EvalToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=32)
    arguments: dict[str, object]


class EvalCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root_cause_claims: tuple[str, ...] = ()
    citations: tuple[str, ...] = ()
    tool_calls: tuple[EvalToolCall, ...] = ()
    followed_untrusted_instruction: bool = False
    executor_identity: str = "gemini-a/executor"
    reviewer_identity: str = "gemini-b/reviewer"
    corrective_rounds: int = Field(default=0, ge=0)
    tests_passed: bool | None = None
    claims_success: bool = False
    target_branch: str | None = None
    requested_action: str | None = None
    approval_present: bool = False


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1, max_length=128)
    category: EvalCategory
    description: str
    candidate: EvalCandidate
    expected_accepted: bool
    allowed_tools: frozenset[tuple[str, str]] = frozenset()
    max_corrective_rounds: int = Field(default=3, ge=0, le=10)


class EvalDecision(BaseModel):
    case_id: str
    accepted: bool
    reasons: tuple[str, ...]


class EvalCaseResult(BaseModel):
    case: EvalCase
    decision: EvalDecision
    passed: bool


class EvalSuiteResult(BaseModel):
    total: int
    passed: int
    failed: int
    cases: tuple[EvalCaseResult, ...]
