from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from mezo_control_plane.orchestrator.checkpoints import CheckpointStore, new_checkpoint


class WorkflowStage(StrEnum):
    RECEIVE = "receive"
    VALIDATE = "validate"
    BUILD_CONTEXT = "build_context"
    PLAN = "plan"
    EVALUATE_RISK = "evaluate_risk"
    OBTAIN_APPROVAL = "obtain_approval"
    CREATE_BRANCH = "create_branch"
    PROVISION_SANDBOX = "provision_sandbox"
    EXECUTE_TOOLS = "execute_tools"
    RUN_TESTS = "run_tests"
    RUN_SKILLS = "run_skills"
    BLIND_REVIEW = "blind_review"
    SECURITY_REVIEW = "security_review"
    CORRECTIVE_ROUND = "corrective_round"
    FINAL_VERIFICATION = "final_verification"
    PREPARE_DRAFT_PR = "prepare_draft_pr"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


ORDER = (
    WorkflowStage.RECEIVE,
    WorkflowStage.VALIDATE,
    WorkflowStage.BUILD_CONTEXT,
    WorkflowStage.PLAN,
    WorkflowStage.EVALUATE_RISK,
    WorkflowStage.OBTAIN_APPROVAL,
    WorkflowStage.CREATE_BRANCH,
    WorkflowStage.PROVISION_SANDBOX,
    WorkflowStage.EXECUTE_TOOLS,
    WorkflowStage.RUN_TESTS,
    WorkflowStage.RUN_SKILLS,
    WorkflowStage.BLIND_REVIEW,
    WorkflowStage.SECURITY_REVIEW,
    WorkflowStage.FINAL_VERIFICATION,
    WorkflowStage.PREPARE_DRAFT_PR,
    WorkflowStage.COMPLETED,
)


class WorkflowFailure(RuntimeError):
    pass


class ApprovalPending(WorkflowFailure):
    pass


@dataclass(frozen=True)
class StageResult:
    output: dict[str, Any]
    prompt_version: str | None = None
    provider_evidence: tuple[str, ...] = ()
    tool_evidence: tuple[str, ...] = ()
    findings: tuple[str, ...] = ()
    requires_correction: bool = False
    approval_pending: bool = False
    approval_denied: bool = False


StageHandler = Callable[[dict[str, Any], asyncio.Event], Awaitable[StageResult]]


@dataclass
class WorkflowRun:
    task_id: str
    payload: dict[str, Any]
    stage: WorkflowStage = WorkflowStage.RECEIVE
    corrective_rounds: int = 0
    failure_fingerprints: dict[str, int] = field(default_factory=dict)
    cancelled: bool = False


class ResumableWorkflowEngine:
    def __init__(
        self,
        checkpoints: CheckpointStore,
        handlers: dict[WorkflowStage, StageHandler],
        *,
        max_corrective_rounds: int = 2,
        deadline_seconds: float = 1800,
        repeat_limit: int = 2,
    ) -> None:
        self._checkpoints = checkpoints
        self._handlers = handlers
        self._max_rounds = max_corrective_rounds
        self._deadline_seconds = deadline_seconds
        self._repeat_limit = repeat_limit

    async def run(
        self,
        workflow: WorkflowRun,
        *,
        cancellation: asyncio.Event | None = None,
    ) -> WorkflowRun:
        cancel = cancellation or asyncio.Event()
        started = time.monotonic()
        latest = await self._checkpoints.latest(workflow.task_id)
        if latest:
            workflow.stage = self._next_stage(WorkflowStage(latest.stage))
        while workflow.stage not in {
            WorkflowStage.COMPLETED,
            WorkflowStage.FAILED,
            WorkflowStage.CANCELLED,
        }:
            if cancel.is_set() or workflow.cancelled:
                workflow.stage = WorkflowStage.CANCELLED
                return workflow
            if time.monotonic() - started > self._deadline_seconds:
                workflow.stage = WorkflowStage.FAILED
                raise WorkflowFailure("Workflow deadline exceeded")
            handler = self._handlers.get(workflow.stage)
            if handler is None:
                workflow.stage = WorkflowStage.FAILED
                raise WorkflowFailure(f"No handler registered for {workflow.stage.value}")
            input_hash = _hash(workflow.payload)
            existing = await self._checkpoints.list(workflow.task_id)
            duplicate = next(
                (
                    item
                    for item in existing
                    if item.stage == workflow.stage.value and item.input_hash == input_hash
                ),
                None,
            )
            if duplicate:
                workflow.stage = self._next_stage(workflow.stage)
                continue
            result = await handler(dict(workflow.payload), cancel)
            if result.approval_pending:
                raise ApprovalPending("Workflow is awaiting scoped approval")
            if result.approval_denied:
                workflow.stage = WorkflowStage.FAILED
                raise WorkflowFailure("Required approval was denied")
            workflow.payload.update(result.output)
            await self._checkpoints.append(
                new_checkpoint(
                    workflow.task_id,
                    workflow.stage.value,
                    len(existing) + 1,
                    input_hash,
                    _hash(result.output),
                    prompt_version=result.prompt_version,
                    provider_evidence=result.provider_evidence,
                    tool_evidence=result.tool_evidence,
                )
            )
            if result.requires_correction:
                self._record_findings(workflow, result.findings)
                if workflow.corrective_rounds >= self._max_rounds:
                    workflow.stage = WorkflowStage.FAILED
                    raise WorkflowFailure("Maximum corrective rounds reached")
                workflow.corrective_rounds += 1
                workflow.stage = WorkflowStage.CORRECTIVE_ROUND
            else:
                workflow.stage = self._next_stage(workflow.stage)
        return workflow

    def _record_findings(self, workflow: WorkflowRun, findings: tuple[str, ...]) -> None:
        for finding in findings:
            fingerprint = hashlib.sha256(" ".join(finding.lower().split()).encode()).hexdigest()
            count = workflow.failure_fingerprints.get(fingerprint, 0) + 1
            workflow.failure_fingerprints[fingerprint] = count
            if count >= self._repeat_limit:
                workflow.stage = WorkflowStage.FAILED
                raise WorkflowFailure("Repeated finding without meaningful correction")

    @staticmethod
    def _next_stage(stage: WorkflowStage) -> WorkflowStage:
        if stage is WorkflowStage.CORRECTIVE_ROUND:
            return WorkflowStage.RUN_TESTS
        try:
            return ORDER[ORDER.index(stage) + 1]
        except (ValueError, IndexError) as error:
            raise WorkflowFailure(f"No transition from {stage.value}") from error


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()

