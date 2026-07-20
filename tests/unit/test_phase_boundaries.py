from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mezo_control_plane.agents.contracts import FinalVerifierInput
from mezo_control_plane.agents.verification import verify_final_evidence
from mezo_control_plane.policies.loader import PolicyLoadError, load_policy_rules
from mezo_control_plane.sandbox.manager import CommandRunner
from mezo_control_plane.sandbox.policies import FilesystemPolicy
from mezo_control_plane.tools.builtins import BuiltinToolSet
from mezo_control_plane.tools.filesystem import FilesystemTools


def test_builtin_registry_contains_every_controlled_tool(tmp_path: Path) -> None:
    policy = FilesystemPolicy(tmp_path)
    registry = BuiltinToolSet(
        FilesystemTools(policy), CommandRunner(policy, allowed_executables=frozenset({"git"}))
    ).registry()
    assert set(registry.registered()) == {
        ("read_file", "1"),
        ("list_directory", "1"),
        ("search_code", "1"),
        ("apply_patch", "1"),
        ("run_command", "1"),
        ("run_tests", "1"),
        ("git_status", "1"),
        ("git_diff", "1"),
        ("prepare_pull_request", "1"),
    }


def test_declarative_policy_loads_deterministically_and_rejects_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "policy.yml"
    path.write_text(
        "- rule_id: global\n  version: '1'\n  priority: 40\n  effect: deny\n"
        "  actions: [deploy]\n  reason: blocked\n",
        encoding="utf-8",
    )
    assert load_policy_rules(path)[0].rule_id == "global"
    path.write_text(path.read_text(encoding="utf-8") * 2, encoding="utf-8")
    with pytest.raises(PolicyLoadError, match="unique"):
        load_policy_rules(path)


def test_final_verifier_rejects_stale_and_missing_evidence() -> None:
    now = datetime.now(UTC)
    result = verify_final_evidence(
        FinalVerifierInput(
            acceptance_criteria=("tests",),
            completed_plan_steps=("tests",),
            diff_hash="a" * 64,
            test_evidence=(),
            guard_receipts=(),
            review_findings=(),
            approvals=(),
            repository_head="b" * 40,
            expected_base="c" * 40,
            evidence_created_at=now - timedelta(hours=2),
            verification_time=now,
        ),
        max_age=timedelta(hours=1),
    )
    assert not result.ready
    assert "test_evidence" in result.missing_evidence
    assert "base_branch_moved" in result.stale_evidence
