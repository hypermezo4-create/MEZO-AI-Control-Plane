from mezo_control_plane.queue.cancellation import CancellationResult
from mezo_control_plane.queue.dead_letter_queue import DeadLetterRecord, ReplayApproval


def test_dead_letter_record_has_a_stable_delivery_identity() -> None:
    record = DeadLetterRecord(
        message_id="message-1",
        task_id="task-1",
        envelope={"task_id": "task-1"},
        priority=2,
        attempts=5,
        failure_class="retry_exhausted",
        error_summary="timeout",
        source_operation="recovery",
        replay_eligible=True,
    )
    assert record.id
    assert record.replayed_message_id is None
    assert record.approval_status is ReplayApproval.PENDING


def test_permanent_failures_are_not_replay_eligible() -> None:
    assert not DeadLetterRecord.replay_allowed_for("permanent_authorization")
    assert not DeadLetterRecord.replay_allowed_for("permanent_validation")
    assert DeadLetterRecord.replay_allowed_for("retry_exhaustion")


def test_cancellation_result_is_machine_readable() -> None:
    assert CancellationResult.CANCELLED == "cancelled"
