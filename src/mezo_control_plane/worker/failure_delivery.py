from datetime import UTC, datetime

from mezo_control_plane.queue.consumer import ClaimedTask, TaskConsumer
from mezo_control_plane.queue.dead_letter_queue import DeadLetterQueue, DeadLetterRecord
from mezo_control_plane.queue.retry_scheduler import RetryScheduler
from mezo_control_plane.worker.failure_classification import ExecutionFailure


class QueueFailureDispatcher:
    """Applies a durable failure decision to Redis without waiting inside a worker."""

    def __init__(
        self,
        consumer: TaskConsumer,
        retries: RetryScheduler,
        dead_letters: DeadLetterQueue,
        worker_id: str,
    ) -> None:
        self._consumer = consumer
        self._retries = retries
        self._dead_letters = dead_letters
        self._worker_id = worker_id

    async def __call__(self, delivery: ClaimedTask, failure: ExecutionFailure) -> None:
        envelope: dict[str, object] = {
            "message_id": delivery.message_id,
            "task_id": str(delivery.task.id),
            "task_json": delivery.task.model_dump_json(),
            "attempt": delivery.attempt,
            "priority": int(delivery.priority),
            "enqueued_at": delivery.task.created_at.isoformat(),
        }
        scheduled = await self._retries.schedule_failure(envelope, failure)
        if scheduled.exhausted:
            now = datetime.now(UTC)
            await self._dead_letters.finalize(
                DeadLetterRecord(
                    message_id=delivery.message_id,
                    task_id=str(delivery.task.id),
                    envelope=envelope,
                    priority=int(delivery.priority),
                    attempts=delivery.attempt + 1,
                    failure_class=failure.classification.value,
                    error_summary=failure.summary,
                    first_failed_at=now,
                    final_failed_at=now,
                    worker_id=self._worker_id,
                    source_operation="execution",
                    replay_eligible=failure.retryable,
                )
            )
        await self._consumer.acknowledge(delivery)
