from datetime import UTC, datetime

from mezo_control_plane.core.domain import AuditEvent, TaskRecord, TaskState
from mezo_control_plane.core.errors import InvalidTransition

_ALLOWED: dict[TaskState, frozenset[TaskState]] = {
    TaskState.RECEIVED: frozenset(
        {TaskState.VALIDATED, TaskState.CONTEXT_READY, TaskState.FAILED, TaskState.CANCELLED}
    ),
    TaskState.VALIDATED: frozenset(
        {TaskState.QUEUED, TaskState.AWAITING_APPROVAL, TaskState.FAILED, TaskState.CANCELLED}
    ),
    TaskState.AWAITING_APPROVAL: frozenset(
        {TaskState.QUEUED, TaskState.FAILED, TaskState.CANCELLED}
    ),
    TaskState.QUEUED: frozenset(
        {TaskState.PLANNING, TaskState.FAILED, TaskState.CANCELLED}
    ),
    TaskState.PLANNING: frozenset(
        {TaskState.EXECUTING, TaskState.AWAITING_APPROVAL, TaskState.FAILED, TaskState.CANCELLED}
    ),
    TaskState.CONTEXT_READY: frozenset({TaskState.PLANNED, TaskState.FAILED, TaskState.CANCELLED}),
    TaskState.PLANNED: frozenset(
        {TaskState.APPROVAL_REQUIRED, TaskState.EXECUTING, TaskState.FAILED, TaskState.CANCELLED}
    ),
    TaskState.APPROVAL_REQUIRED: frozenset(
        {TaskState.EXECUTING, TaskState.CANCELLED, TaskState.FAILED}
    ),
    TaskState.EXECUTING: frozenset(
        {TaskState.TESTING, TaskState.VERIFYING, TaskState.FAILED, TaskState.CANCELLED}
    ),
    TaskState.TESTING: frozenset(
        {TaskState.GUARDING, TaskState.FIXING, TaskState.FAILED, TaskState.CANCELLED}
    ),
    TaskState.GUARDING: frozenset(
        {TaskState.REVIEWING, TaskState.FIXING, TaskState.FAILED, TaskState.CANCELLED}
    ),
    TaskState.VERIFYING: frozenset({TaskState.REVIEWING, TaskState.EXECUTING, TaskState.FAILED}),
    TaskState.REVIEWING: frozenset(
        {
            TaskState.EXECUTING,
            TaskState.FIXING,
            TaskState.READY_FOR_PR,
            TaskState.FAILED,
            TaskState.CANCELLED,
        }
    ),
    TaskState.FIXING: frozenset({TaskState.EXECUTING, TaskState.FAILED, TaskState.CANCELLED}),
    TaskState.READY_FOR_PR: frozenset({TaskState.PR_OPENED, TaskState.COMPLETED, TaskState.FAILED}),
    TaskState.PR_OPENED: frozenset({TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}),
    TaskState.COMPLETED: frozenset(),
    TaskState.FAILED: frozenset(),
    TaskState.CANCELLED: frozenset(),
}


def transition(
    task: TaskRecord,
    target: TaskState,
    evidence: str | None = None,
    *,
    idempotency_key: str | None = None,
    actor: str = "control-plane",
) -> TaskRecord:
    key = idempotency_key or f"transition:{task.state}:{target}:{evidence or ''}"
    if any(event.idempotency_key == key for event in task.audit_events):
        return task
    if target not in _ALLOWED[task.state]:
        raise InvalidTransition(f"Cannot transition task from {task.state} to {target}")
    source = task.state
    task.state = target
    task.updated_at = datetime.now(UTC)
    if evidence:
        task.evidence.append(evidence)
    task.audit_events.append(
        AuditEvent(
            action="task.transition",
            actor=actor,
            idempotency_key=key,
            detail=f"{source}->{target}",
        )
    )
    return task
