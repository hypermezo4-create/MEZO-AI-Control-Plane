from datetime import UTC, datetime, timedelta

import pytest

from mezo_control_plane.policies.approvals import ApprovalStore, ApprovalValidationError
from mezo_control_plane.policies.engine import PolicyEngine
from mezo_control_plane.policies.models import (
    ApprovalDecision,
    ApprovalRecord,
    PolicyEffect,
    PolicyPriority,
    PolicyRequest,
    PolicyRule,
    RiskInput,
)


def _rule(rule_id: str, priority: PolicyPriority, effect: PolicyEffect, reason: str) -> PolicyRule:
    return PolicyRule(
        rule_id=rule_id,
        version="1",
        priority=priority,
        effect=effect,
        actions=frozenset({"write"}),
        reason=reason,
    )


def test_global_deny_cannot_be_weakened_and_decision_is_deterministic() -> None:
    engine = PolicyEngine(
        (
            _rule("repo-allow", PolicyPriority.REPOSITORY, PolicyEffect.ALLOW, "repo allows"),
            _rule("global-deny", PolicyPriority.GLOBAL, PolicyEffect.DENY, "global denies"),
        )
    )
    request = PolicyRequest(action="write", repository="owner/repo", actor_role="owner")
    first = engine.decide(request)
    second = engine.decide(request)
    assert first.effect is PolicyEffect.DENY
    assert first.decision_hash == second.decision_hash


@pytest.mark.parametrize(
    ("risk", "path"),
    [
        (RiskInput(migration_changed=True), "alembic/versions/2.py"),
        (RiskInput(workflow_changed=True), ".github/workflows/ci.yml"),
        (RiskInput(deployment_requested=True), "fly.toml"),
        (RiskInput(network_expanded=True), "policies/network.yml"),
    ],
)
def test_mandatory_high_risk_actions_require_approval(risk: RiskInput, path: str) -> None:
    decision = PolicyEngine().decide(
        PolicyRequest(
            action="write", repository="owner/repo", actor_role="owner", paths=(path,), risk=risk
        )
    )
    assert decision.effect is PolicyEffect.APPROVAL


def _approval(now: datetime, **updates: object) -> ApprovalRecord:
    values: dict[str, object] = {
        "approval_id": "approval-1",
        "task_id": "task-1",
        "scope": ("alembic/versions/2.py",),
        "decision": ApprovalDecision.APPROVED,
        "actor": "owner-1",
        "actor_role": "owner",
        "reason": "reviewed migration",
        "requested_at": now - timedelta(minutes=2),
        "decided_at": now - timedelta(minutes=1),
        "expires_at": now + timedelta(minutes=10),
        "base_sha": "a" * 40,
        "plan_hash": "b" * 64,
        "diff_hash": "c" * 64,
        "policy_version": "1",
        "evidence_hash": "d" * 64,
    }
    values.update(updates)
    return ApprovalRecord.model_validate(values)


@pytest.mark.asyncio
async def test_approval_is_scoped_expiring_and_one_time() -> None:
    now = datetime.now(UTC)
    store = ApprovalStore()
    await store.add(_approval(now))
    await store.consume(
        "approval-1",
        task_id="task-1",
        scope=("alembic/versions/2.py",),
        base_sha="a" * 40,
        plan_hash="b" * 64,
        diff_hash="c" * 64,
        actor_role="operator",
        now=now,
    )
    with pytest.raises(ApprovalValidationError, match="already used"):
        await store.consume(
            "approval-1",
            task_id="task-1",
            scope=("alembic/versions/2.py",),
            base_sha="a" * 40,
            plan_hash="b" * 64,
            diff_hash="c" * 64,
            actor_role="operator",
            now=now,
        )


@pytest.mark.asyncio
async def test_approval_invalidates_on_expiry_base_plan_diff_and_scope() -> None:
    now = datetime.now(UTC)
    cases = [
        ({"now": now + timedelta(hours=1)}, "expired"),
        ({"base_sha": "f" * 40}, "base or plan"),
        ({"plan_hash": "f" * 64}, "base or plan"),
        ({"diff_hash": "f" * 64}, "diff scope"),
        ({"scope": ("other",)}, "scope mismatch"),
    ]
    for index, (change, message) in enumerate(cases):
        store = ApprovalStore()
        await store.add(_approval(now, approval_id=f"approval-{index}"))
        arguments = {
            "task_id": "task-1",
            "scope": ("alembic/versions/2.py",),
            "base_sha": "a" * 40,
            "plan_hash": "b" * 64,
            "diff_hash": "c" * 64,
            "actor_role": "operator",
            "now": now,
        }
        arguments.update(change)
        with pytest.raises(ApprovalValidationError, match=message):
            await store.consume(f"approval-{index}", **arguments)  # type: ignore[arg-type]
