import pytest

from mezo_control_plane.core.domain import TaskRecord, TaskRequest, TaskState
from mezo_control_plane.core.errors import InvalidTransition
from mezo_control_plane.orchestrator.state_machine import transition


def make_task() -> TaskRecord:
    return TaskRecord(request=TaskRequest(repository="owner/repo", instruction="Fix the bug"))


def test_received_task_can_build_context() -> None:
    task = transition(make_task(), TaskState.CONTEXT_READY, "context")
    assert task.state is TaskState.CONTEXT_READY
    assert task.evidence == ["context"]


def test_received_task_cannot_skip_to_execution() -> None:
    with pytest.raises(InvalidTransition):
        transition(make_task(), TaskState.EXECUTING)


def test_transition_records_an_auditable_idempotency_key() -> None:
    task = make_task()
    transition(task, TaskState.VALIDATED, "request-valid", idempotency_key="request-1")
    transition(task, TaskState.VALIDATED, "request-valid", idempotency_key="request-1")

    assert task.state is TaskState.VALIDATED
    assert [event.idempotency_key for event in task.audit_events] == ["request-1"]
    assert task.audit_events[0].detail == "received->validated"


def test_explicit_lifecycle_reaches_pull_request_state() -> None:
    task = make_task()
    for target in (
        TaskState.VALIDATED,
        TaskState.QUEUED,
        TaskState.PLANNING,
        TaskState.EXECUTING,
        TaskState.TESTING,
        TaskState.GUARDING,
        TaskState.REVIEWING,
        TaskState.READY_FOR_PR,
        TaskState.PR_OPENED,
        TaskState.COMPLETED,
    ):
        transition(task, target)

    assert task.state is TaskState.COMPLETED
    assert len(task.audit_events) == 10
