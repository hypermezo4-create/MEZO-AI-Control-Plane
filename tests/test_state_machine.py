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
