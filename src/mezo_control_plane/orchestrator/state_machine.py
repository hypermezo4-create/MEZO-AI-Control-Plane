from datetime import UTC, datetime

from mezo_control_plane.core.domain import TaskRecord, TaskState
from mezo_control_plane.core.errors import InvalidTransition

_ALLOWED: dict[TaskState, frozenset[TaskState]] = {
    TaskState.RECEIVED: frozenset({TaskState.CONTEXT_READY, TaskState.FAILED, TaskState.CANCELLED}),
    TaskState.CONTEXT_READY: frozenset({TaskState.PLANNED, TaskState.FAILED, TaskState.CANCELLED}),
    TaskState.PLANNED: frozenset(
        {TaskState.APPROVAL_REQUIRED, TaskState.EXECUTING, TaskState.FAILED, TaskState.CANCELLED}
    ),
    TaskState.APPROVAL_REQUIRED: frozenset(
        {TaskState.EXECUTING, TaskState.CANCELLED, TaskState.FAILED}
    ),
    TaskState.EXECUTING: frozenset({TaskState.VERIFYING, TaskState.FAILED, TaskState.CANCELLED}),
    TaskState.VERIFYING: frozenset({TaskState.REVIEWING, TaskState.EXECUTING, TaskState.FAILED}),
    TaskState.REVIEWING: frozenset(
        {TaskState.EXECUTING, TaskState.READY_FOR_PR, TaskState.FAILED}
    ),
    TaskState.READY_FOR_PR: frozenset({TaskState.COMPLETED, TaskState.FAILED}),
    TaskState.COMPLETED: frozenset(),
    TaskState.FAILED: frozenset(),
    TaskState.CANCELLED: frozenset(),
}


def transition(task: TaskRecord, target: TaskState, evidence: str | None = None) -> TaskRecord:
    if target not in _ALLOWED[task.state]:
        raise InvalidTransition(f"Cannot transition task from {task.state} to {target}")
    task.state = target
    task.updated_at = datetime.now(UTC)
    if evidence:
        task.evidence.append(evidence)
    return task
