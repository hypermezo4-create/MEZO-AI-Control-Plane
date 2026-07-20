from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import PurePosixPath

from mezo_control_plane.core.domain import RiskLevel
from mezo_control_plane.core.errors import PolicyDenied
from mezo_control_plane.policies.models import (
    DeterministicPolicyDecision,
    PolicyEffect,
    PolicyRequest,
    PolicyRule,
    RiskInput,
    stable_hash,
)


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    risk: RiskLevel
    approval_required: bool
    reason: str


class PolicyEngine:
    def __init__(self, rules: tuple[PolicyRule, ...] = ()) -> None:
        self._blocked_commands = {"rm", "mkfs", "shutdown", "reboot", "dd"}
        self._protected_roots = {".github/workflows", "migrations", "alembic", "infra/production"}
        self._rules = tuple(sorted(rules, key=lambda rule: (-rule.priority, rule.rule_id)))

    def decide(self, request: PolicyRequest) -> DeterministicPolicyDecision:
        matched = tuple(rule for rule in self._rules if _matches(rule, request))
        mandatory = _mandatory_effect(request.risk, request.paths, request.command)
        strongest = mandatory
        for rule in matched:
            if rule.effect is PolicyEffect.DENY:
                strongest = PolicyEffect.DENY
                break
            if rule.effect is PolicyEffect.APPROVAL and strongest is PolicyEffect.ALLOW:
                strongest = PolicyEffect.APPROVAL
        reasons = tuple(rule.reason for rule in matched) or ("No matching declarative rule",)
        if mandatory is not PolicyEffect.ALLOW:
            reasons = (*reasons, f"Mandatory platform effect: {mandatory.value}")
        risk = assess_risk(request.risk)
        values = {
            "effect": strongest.value,
            "risk": risk.value,
            "reasons": reasons,
            "matched_rules": tuple(rule.rule_id for rule in matched),
            "policy_versions": tuple(sorted({rule.version for rule in matched})),
            "required_skills": tuple(
                sorted({skill for rule in matched for skill in rule.required_skills})
            ),
            "required_checks": tuple(
                sorted({check for rule in matched for check in rule.required_checks})
            ),
            "resource_limits": (("memory_mb", 1024), ("cpu_millis", 1000)),
            "network_limits": (),
            "tool_limits": (("calls", 100), ("changed_files", 100)),
            "reevaluate_when": ("base_sha_changes", "plan_changes", "diff_scope_changes"),
        }
        return DeterministicPolicyDecision.model_validate(
            {**values, "decision_hash": stable_hash(values)}
        )

    def evaluate_command(self, command: list[str]) -> PolicyDecision:
        if not command:
            raise PolicyDenied("Empty commands are not permitted")
        executable = PurePosixPath(command[0]).name
        if executable in self._blocked_commands:
            return PolicyDecision(False, RiskLevel.CRITICAL, True, "Destructive command blocked")
        return PolicyDecision(True, RiskLevel.MEDIUM, False, "Command permitted by base policy")

    def evaluate_paths(self, paths: list[str]) -> PolicyDecision:
        normalized = {str(PurePosixPath(path)) for path in paths}
        protected = sorted(
            path
            for path in normalized
            if any(path == root or path.startswith(f"{root}/") for root in self._protected_roots)
        )
        if protected:
            return PolicyDecision(
                True,
                RiskLevel.HIGH,
                True,
                f"Protected paths require approval: {', '.join(protected)}",
            )
        return PolicyDecision(True, RiskLevel.MEDIUM, False, "No protected paths touched")


def assess_risk(value: RiskInput) -> RiskLevel:
    if value.critical_findings or value.destructive_command or value.secret_changed:
        return RiskLevel.CRITICAL
    if any(
        (
            value.migration_changed,
            value.workflow_changed,
            value.infrastructure_changed,
            value.deployment_requested,
            value.network_expanded,
            value.resource_escalation,
            value.authentication_changed,
            value.authorization_changed,
        )
    ):
        return RiskLevel.HIGH
    if len(value.changed_paths) > 20 or value.changed_bytes > 500_000 or value.dependency_changed:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _mandatory_effect(
    risk: RiskInput, paths: tuple[str, ...], command: tuple[str, ...]
) -> PolicyEffect:
    if risk.destructive_command or (
        command and PurePosixPath(command[0]).name in {"rm", "dd", "mkfs"}
    ):
        return PolicyEffect.DENY
    protected = any(
        path.startswith((".github/workflows/", "alembic/", "migrations/", "infra/production/"))
        for path in paths
    )
    if protected or any(
        (
            risk.migration_changed,
            risk.workflow_changed,
            risk.deployment_requested,
            risk.secret_changed,
            risk.network_expanded,
            risk.resource_escalation,
            risk.critical_findings > 0,
        )
    ):
        return PolicyEffect.APPROVAL
    return PolicyEffect.ALLOW


def _matches(rule: PolicyRule, request: PolicyRequest) -> bool:
    if request.action not in rule.actions:
        return False
    if rule.path_patterns and not any(
        fnmatch.fnmatch(path, pattern) for path in request.paths for pattern in rule.path_patterns
    ):
        return False
    if rule.command_names and (
        not request.command or PurePosixPath(request.command[0]).name not in rule.command_names
    ):
        return False
    if rule.required_roles and request.actor_role not in rule.required_roles:
        return False
    return True
