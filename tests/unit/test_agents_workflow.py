import asyncio
import hashlib

import pytest

from mezo_control_plane.agents.contracts import (
    BlindReviewInput,
    ContextReference,
    PlannerOutput,
)
from mezo_control_plane.orchestrator.checkpoints import InMemoryCheckpointStore
from mezo_control_plane.orchestrator.engine import (
    ApprovalPending,
    ResumableWorkflowEngine,
    StageResult,
    WorkflowFailure,
    WorkflowRun,
    WorkflowStage,
)


def test_blind_review_contract_has_no_executor_persuasion_fields() -> None:
    fields = BlindReviewInput.model_fields
    assert "executor_confidence" not in fields
    assert "executor_narrative" not in fields
    assert "executor_self_review" not in fields


def test_agent_contracts_export_json_schema() -> None:
    schema = PlannerOutput.model_json_schema()
    assert schema["type"] == "object"
    ContextReference(
        citation_id="c1", path="src/a.py", content_hash=hashlib.sha256(b"x").hexdigest()
    )


async def _result(payload: dict[str, object], cancel: asyncio.Event) -> StageResult:
    assert not cancel.is_set()
    return StageResult({"visited": [*payload.get("visited", []), "yes"]})


@pytest.mark.asyncio
async def test_workflow_runs_every_stage_and_checkpoints() -> None:
    store = InMemoryCheckpointStore()
    handlers = {stage: _result for stage in WorkflowStage if stage not in {
        WorkflowStage.COMPLETED, WorkflowStage.FAILED, WorkflowStage.CANCELLED
    }}
    run = WorkflowRun("task-1", {})
    result = await ResumableWorkflowEngine(store, handlers).run(run)
    assert result.stage is WorkflowStage.COMPLETED
    assert len(await store.list("task-1")) == len(handlers) - 1  # corrective is conditional


@pytest.mark.asyncio
async def test_workflow_pauses_and_resumes_approval() -> None:
    store = InMemoryCheckpointStore()
    approved = False

    async def handler(payload: dict[str, object], cancel: asyncio.Event) -> StageResult:
        if payload.get("stage") == "approval" and not approved:
            return StageResult({}, approval_pending=True)
        return StageResult({})

    handlers = {stage: handler for stage in WorkflowStage if stage not in {
        WorkflowStage.COMPLETED, WorkflowStage.FAILED, WorkflowStage.CANCELLED
    }}
    handlers[WorkflowStage.OBTAIN_APPROVAL] = handler
    run = WorkflowRun("task-2", {"stage": "approval"}, WorkflowStage.OBTAIN_APPROVAL)
    with pytest.raises(ApprovalPending):
        await ResumableWorkflowEngine(store, handlers).run(run)
    approved = True
    result = await ResumableWorkflowEngine(store, handlers).run(run)
    assert result.stage is WorkflowStage.COMPLETED


@pytest.mark.asyncio
async def test_workflow_cancellation_is_terminal() -> None:
    cancel = asyncio.Event()
    cancel.set()
    result = await ResumableWorkflowEngine(InMemoryCheckpointStore(), {}).run(
        WorkflowRun("task-3", {}), cancellation=cancel
    )
    assert result.stage is WorkflowStage.CANCELLED


@pytest.mark.asyncio
async def test_repeated_finding_stops_corrective_loop() -> None:
    store = InMemoryCheckpointStore()

    async def rejection(payload: dict[str, object], cancel: asyncio.Event) -> StageResult:
        return StageResult({}, findings=("same critical failure",), requires_correction=True)

    handlers = {stage: _result for stage in WorkflowStage if stage not in {
        WorkflowStage.COMPLETED, WorkflowStage.FAILED, WorkflowStage.CANCELLED
    }}
    handlers[WorkflowStage.BLIND_REVIEW] = rejection
    handlers[WorkflowStage.CORRECTIVE_ROUND] = rejection
    with pytest.raises(WorkflowFailure, match="Repeated finding"):
        await ResumableWorkflowEngine(store, handlers, max_corrective_rounds=3).run(
            WorkflowRun("task-4", {}, WorkflowStage.BLIND_REVIEW)
        )


@pytest.mark.asyncio
async def test_duplicate_stage_invocation_is_idempotent() -> None:
    store = InMemoryCheckpointStore()
    calls = 0

    async def counted(payload: dict[str, object], cancel: asyncio.Event) -> StageResult:
        nonlocal calls
        calls += 1
        return StageResult({"value": 1})

    handlers = {WorkflowStage.RECEIVE: counted, WorkflowStage.VALIDATE: _result}
    engine = ResumableWorkflowEngine(store, handlers)
    with pytest.raises(WorkflowFailure, match="No handler"):
        await engine.run(WorkflowRun("task-5", {}))
    resumed = WorkflowRun("task-5", {})
    with pytest.raises(WorkflowFailure, match="No handler"):
        await engine.run(resumed)
    assert calls == 1
