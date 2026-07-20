from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from pydantic import BaseModel, Field
from redis.asyncio import Redis

from mezo_control_plane.queue.producer import QueueInfrastructureError


class DeadLetterRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    message_id: str
    task_id: str
    envelope: dict[str, object]
    priority: int
    attempts: int
    failure_class: str
    error_summary: str = Field(max_length=1_000)
    first_failed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    final_failed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    worker_id: str | None = None
    source_operation: str
    replay_eligible: bool
    replayed_message_id: str | None = None


class DeadLetterQueue:
    def __init__(self, redis: Redis, prefix: str = "mezo:queue") -> None:
        self._redis = redis
        self._prefix = prefix

    async def finalize(self, record: DeadLetterRecord) -> bool:
        try:
            return bool(
                await cast(Any, self._redis.hsetnx(
                    f"{self._prefix}:dlq", record.message_id, record.model_dump_json()
                ))
            )
        except Exception as error:
            raise QueueInfrastructureError("Redis DLQ finalization failed") from error

    async def get(self, message_id: str) -> DeadLetterRecord | None:
        try:
            raw = await cast(Any, self._redis.hget(f"{self._prefix}:dlq", message_id))
        except Exception as error:
            raise QueueInfrastructureError("Redis DLQ read failed") from error
        return DeadLetterRecord.model_validate_json(raw) if raw else None

    async def list(self) -> list[DeadLetterRecord]:
        try:
            records = await cast(Any, self._redis.hvals(f"{self._prefix}:dlq"))
        except Exception as error:
            raise QueueInfrastructureError("Redis DLQ listing failed") from error
        return [DeadLetterRecord.model_validate_json(item) for item in records]
