from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import IntEnum, StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mezo_control_plane.core.domain import RiskLevel


class PolicyEffect(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    APPROVAL = "approval_required"


class PolicyPriority(IntEnum):
    TASK = 10
    REPOSITORY_PROFILE = 20
    REPOSITORY = 30
    GLOBAL = 40


class PolicyRule(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule_id: str
    version: str
    priority: PolicyPriority
    effect: PolicyEffect
    actions: frozenset[str]
    path_patterns: tuple[str, ...] = ()
    command_names: tuple[str, ...] = ()
    required_roles: frozenset[str] = frozenset()
    required_skills: frozenset[str] = frozenset()
    required_checks: frozenset[str] = frozenset()
    reason: str


class RiskInput(BaseModel):
    changed_paths: tuple[str, ...] = ()
    changed_bytes: int = Field(default=0, ge=0)
    authentication_changed: bool = False
    authorization_changed: bool = False
    secret_changed: bool = False
    migration_changed: bool = False
    workflow_changed: bool = False
    infrastructure_changed: bool = False
    deployment_requested: bool = False
    network_expanded: bool = False
    dependency_changed: bool = False
    destructive_command: bool = False
    resource_escalation: bool = False
    critical_findings: int = Field(default=0, ge=0)


class PolicyRequest(BaseModel):
    action: str
    repository: str
    actor_role: str
    paths: tuple[str, ...] = ()
    command: tuple[str, ...] = ()
    network_hosts: tuple[str, ...] = ()
    risk: RiskInput = Field(default_factory=RiskInput)


class DeterministicPolicyDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    effect: PolicyEffect
    risk: RiskLevel
    reasons: tuple[str, ...]
    matched_rules: tuple[str, ...]
    policy_versions: tuple[str, ...]
    required_skills: tuple[str, ...]
    required_checks: tuple[str, ...]
    resource_limits: tuple[tuple[str, int], ...]
    network_limits: tuple[str, ...]
    tool_limits: tuple[tuple[str, int], ...]
    reevaluate_when: tuple[str, ...]
    decision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class ApprovalDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


class ApprovalRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    approval_id: str
    task_id: str
    scope: tuple[str, ...]
    decision: ApprovalDecision
    actor: str
    actor_role: str
    reason: str
    requested_at: datetime
    decided_at: datetime
    expires_at: datetime
    one_time: bool = True
    base_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    diff_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    policy_version: str
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_times(self) -> ApprovalRecord:
        if self.decided_at < self.requested_at or self.expires_at <= self.decided_at:
            raise ValueError("Approval timestamps are invalid")
        return self


def stable_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
