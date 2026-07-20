from __future__ import annotations

from mezo_control_plane.agents.prompts import PLANNER_SYSTEM
from mezo_control_plane.core.domain import ModelMessage, ModelRequest, TaskRecord, TaskState
from mezo_control_plane.model_router.router import ModelRole, ModelRouter
from mezo_control_plane.orchestrator.state_machine import transition
from mezo_control_plane.policies.engine import PolicyEngine


class WorkflowEngine:
    def __init__(self, model_router: ModelRouter, policy_engine: PolicyEngine) -> None:
        self._models = model_router
        self._policy = policy_engine

    async def plan(self, task: TaskRecord, repository_context: str) -> TaskRecord:
        transition(task, TaskState.CONTEXT_READY, "repository-context-built")
        response = await self._models.generate(
            ModelRole.PLANNER,
            ModelRequest(
                system_instruction=PLANNER_SYSTEM,
                messages=[
                    ModelMessage(role="user", content=task.request.instruction),
                    ModelMessage(role="user", content=repository_context),
                ],
            ),
        )
        task.evidence.append(f"plan:{response.provider}:{response.model}:{response.text}")
        transition(task, TaskState.PLANNED, "plan-generated")
        return task

    def authorize_paths(self, task: TaskRecord, changed_paths: list[str]) -> TaskRecord:
        decision = self._policy.evaluate_paths(changed_paths)
        task.risk = decision.risk
        task.evidence.append(f"policy:{decision.reason}")
        if decision.approval_required:
            transition(task, TaskState.APPROVAL_REQUIRED, "human-approval-required")
        else:
            transition(task, TaskState.EXECUTING, "execution-authorized")
        return task
