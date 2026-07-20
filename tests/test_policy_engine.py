from mezo_control_plane.core.domain import RiskLevel
from mezo_control_plane.policies.engine import PolicyEngine


def test_workflow_change_requires_approval() -> None:
    decision = PolicyEngine().evaluate_paths([".github/workflows/deploy.yml"])
    assert decision.allowed
    assert decision.approval_required
    assert decision.risk is RiskLevel.HIGH


def test_destructive_command_is_blocked() -> None:
    decision = PolicyEngine().evaluate_command(["rm", "-rf", "/"])
    assert not decision.allowed
    assert decision.approval_required
    assert decision.risk is RiskLevel.CRITICAL
