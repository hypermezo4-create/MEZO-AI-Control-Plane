import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mezo_control_plane.github.client import GitHubClient
from mezo_control_plane.orchestrator.checkpoints import InMemoryCheckpointStore
from mezo_control_plane.orchestrator.engine import (
    ResumableWorkflowEngine,
    StageResult,
    WorkflowRun,
    WorkflowStage,
)
from mezo_control_plane.policies.approvals import ApprovalStore
from mezo_control_plane.policies.engine import PolicyEngine
from mezo_control_plane.policies.models import (
    ApprovalDecision,
    ApprovalRecord,
    PolicyEffect,
    PolicyRequest,
    RiskInput,
)
from mezo_control_plane.repository_intelligence.context_builder import (
    ContextBuilder,
    ContextRequest,
)
from mezo_control_plane.repository_intelligence.scanner import RepositoryScanner
from mezo_control_plane.sandbox.policies import FilesystemPolicy
from mezo_control_plane.skills.runtime import (
    SkillFile,
    SkillLoader,
    SkillManifest,
    SkillManifestEntry,
)
from mezo_control_plane.tools.contracts import ApplyPatchInput, StructuredPatchFile
from mezo_control_plane.tools.filesystem import FilesystemTools


class GitHubFixture:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []

    async def request(
        self,
        method: str,
        path: str,
        *,
        token: str,
        json_body: dict[str, object] | None = None,
    ) -> tuple[int, dict[str, object], dict[str, str]]:
        assert token
        self.requests.append((method, path))
        if path.endswith("/git/refs"):
            return 201, {"ref": json_body["ref"] if json_body else ""}, {}
        if path.endswith("/pulls"):
            return 201, {"number": 1, "html_url": "https://example.test/draft/1"}, {}
        return 200, {}, {}


@pytest.mark.asyncio
async def test_authenticated_task_to_draft_pr_payload_without_external_write(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "AGENTS.md").write_text("Preserve tests and require approval.", encoding="utf-8")
    (repository / "service.py").write_text("def result():\n    return 1\n", encoding="utf-8")
    (repository / "test_service.py").write_text("def test_result(): pass\n", encoding="utf-8")
    scanner = RepositoryScanner(repository)
    context = ContextBuilder(repository).build(
        ContextRequest("owner/repo", "a" * 40, "change result service", max_tokens=3000)
    )
    assert scanner.rules() and context

    risk = PolicyEngine().decide(
        PolicyRequest(
            action="write",
            repository="owner/repo",
            actor_role="operator",
            paths=("service.py",),
            risk=RiskInput(changed_paths=("service.py",)),
        )
    )
    assert risk.effect is PolicyEffect.ALLOW

    now = datetime.now(UTC)
    approvals = ApprovalStore()
    approval = ApprovalRecord(
        approval_id="approval-1",
        task_id="task-1",
        scope=("service.py",),
        decision=ApprovalDecision.APPROVED,
        actor="owner",
        actor_role="owner",
        reason="fixture approval",
        requested_at=now - timedelta(minutes=2),
        decided_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(minutes=10),
        base_sha="a" * 40,
        plan_hash="b" * 64,
        diff_hash=None,
        policy_version="1",
        evidence_hash="c" * 64,
    )
    await approvals.add(approval)
    await approvals.consume(
        "approval-1",
        task_id="task-1",
        scope=("service.py",),
        base_sha="a" * 40,
        plan_hash="b" * 64,
        diff_hash=None,
        actor_role="operator",
        now=now,
    )

    tools = FilesystemTools(FilesystemPolicy(repository))
    original = (repository / "service.py").read_bytes()
    await tools.apply_patch(
        ApplyPatchInput(
            files=(
                StructuredPatchFile(
                    path="service.py",
                    base_hash=hashlib.sha256(original).hexdigest(),
                    content="def result():\n    return 2\n",
                ),
            )
        )
    )

    skill_text = "---\nname: test-guard\nversion: 1.0.0\n---\nReview test evidence.\n"
    skill_path = tmp_path / "skills/test-guard/SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text(skill_text, encoding="utf-8")
    manifest = SkillManifest(
        repository="owner/skills",
        commit_sha="d" * 40,
        skills=(
            SkillManifestEntry(
                name="test-guard",
                version="1.0.0",
                files=(
                    SkillFile(
                        path="skills/test-guard/SKILL.md",
                        sha256=hashlib.sha256(skill_path.read_bytes()).hexdigest(),
                    ),
                ),
            ),
        ),
    )
    assert SkillLoader(
        tmp_path,
        manifest,
        approved_repository="owner/skills",
        approved_commit="d" * 40,
    ).load("test-guard")

    async def stage(payload: dict[str, object], cancel: asyncio.Event) -> StageResult:
        assert not cancel.is_set()
        return StageResult({f"stage_{len(payload)}": "ok"})

    handlers = {
        stage_name: stage
        for stage_name in WorkflowStage
        if stage_name
        not in {WorkflowStage.COMPLETED, WorkflowStage.FAILED, WorkflowStage.CANCELLED}
    }
    workflow = await ResumableWorkflowEngine(InMemoryCheckpointStore(), handlers).run(
        WorkflowRun("task-1", {"authenticated": True})
    )
    assert workflow.stage is WorkflowStage.COMPLETED

    github = GitHubClient(GitHubFixture(), allowed_repositories=frozenset({"owner/repo"}))
    fixture_credential = "installation-fixture"  # noqa: S105
    branch = await github.create_branch(
        "owner/repo", "a" * 40, "task-1", "controlled delivery", fixture_credential
    )
    number, url = await github.create_draft_pull_request(
        "owner/repo",
        "main",
        branch,
        "Controlled delivery",
        "Base SHA, plan, tests, guards, findings, risk, approvals, limitations and rollback.",
        fixture_credential,
    )
    assert number == 1 and url.endswith("/1")


@pytest.mark.asyncio
async def test_failed_required_check_prevents_pr_preparation() -> None:
    async def stage(payload: dict[str, object], cancel: asyncio.Event) -> StageResult:
        if payload.get("tests") == "failed":
            raise RuntimeError("required tests failed")
        return StageResult({})

    engine = ResumableWorkflowEngine(
        InMemoryCheckpointStore(), {WorkflowStage.FINAL_VERIFICATION: stage}
    )
    with pytest.raises(RuntimeError, match="required tests"):
        await engine.run(
            WorkflowRun("task-failed", {"tests": "failed"}, WorkflowStage.FINAL_VERIFICATION)
        )
