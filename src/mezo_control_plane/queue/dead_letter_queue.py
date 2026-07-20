from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, cast
from uuid import uuid4

from pydantic import BaseModel, Field
from redis.asyncio import Redis

from mezo_control_plane.queue.producer import QueueInfrastructureError

_FINALIZE_SCRIPT = """
local existing=redis.call('HGET', KEYS[1], ARGV[1])
if existing then return {0,existing} end
redis.call('HSET', KEYS[1], ARGV[1], ARGV[3])
redis.call('HSET', KEYS[2], ARGV[2], ARGV[1])
return {1,ARGV[3]}
"""
_REPLAY_SCRIPT = """
local raw=redis.call('HGET', KEYS[1], ARGV[1])
if not raw then return {0,'not-found'} end
local record=cjson.decode(raw)
if record.replayed_message_id ~= cjson.null and record.replayed_message_id ~= nil then
  return {0,'already-replayed'}
end
if record.replay_eligible ~= true or record.approval_status ~= 'approved' then
  return {0,'not-approved'}
end
if redis.call('SISMEMBER', KEYS[2], record.task_id) == 1 then return {0,'cancelled'} end
local task=cjson.decode(record.envelope.task_json)
if task.state == 'completed' or task.state == 'cancelled' then return {0,'terminal'} end
local envelope=record.envelope
envelope.message_id=ARGV[2]
envelope.owner_token=nil; envelope.worker_id=nil; envelope.claimed_at=nil
envelope.lease_expires_at=nil
record.replayed_message_id=ARGV[2]
record.replayed_at=ARGV[3]
redis.call('HSET', KEYS[1], ARGV[1], cjson.encode(record))
      redis.call('RPUSH', KEYS[4 + tonumber(envelope.priority)], cjson.encode(envelope))
return {1,ARGV[2]}
"""


class ReplayApproval(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


class ReplayResult(StrEnum):
    REPLAYED = "replayed"
    NOT_FOUND = "not-found"
    ALREADY_REPLAYED = "already-replayed"
    NOT_APPROVED = "not-approved"
    CANCELLED = "cancelled"
    TERMINAL = "terminal"


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
    evidence_reference: str | None = None
    source_operation: str
    replay_eligible: bool
    approval_status: ReplayApproval = ReplayApproval.PENDING
    replayed_at: datetime | None = None
    replayed_message_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    attempt_history: list[dict[str, object]] = Field(default_factory=list)
    cancelled: bool = False

    @classmethod
    def replay_allowed_for(cls, failure_class: str) -> bool:
        return failure_class not in {"permanent_authorization", "permanent_validation"}


class DeadLetterQueue:
    def __init__(self, redis: Redis, prefix: str = "mezo:queue") -> None:
        self._redis = redis
        self._prefix = prefix

    async def finalize(self, record: DeadLetterRecord) -> DeadLetterRecord:
        record = record.model_copy(
            update={
                "replay_eligible": record.replay_eligible
                and DeadLetterRecord.replay_allowed_for(record.failure_class)
            }
        )
        try:
            result = await cast(
                Any,
                self._redis.eval(
                    _FINALIZE_SCRIPT,
                    2,
                    f"{self._prefix}:dlq",
                    f"{self._prefix}:dlq-task-index",
                    record.message_id,
                    record.task_id,
                    record.model_dump_json(),
                ),
            )
        except Exception as error:
            raise QueueInfrastructureError("Redis DLQ finalization failed") from error
        return DeadLetterRecord.model_validate_json(result[1])

    async def get(self, record_id: str) -> DeadLetterRecord | None:
        try:
            records = await cast(Any, self._redis.hvals(f"{self._prefix}:dlq"))
        except Exception as error:
            raise QueueInfrastructureError("Redis DLQ read failed") from error
        for raw in records:
            record = DeadLetterRecord.model_validate_json(raw)
            if record.id == record_id or record.message_id == record_id:
                return record
        return None

    async def get_by_task(self, task_id: str) -> DeadLetterRecord | None:
        try:
            message_id = await cast(
                Any, self._redis.hget(f"{self._prefix}:dlq-task-index", task_id)
            )
            raw = (
                await cast(Any, self._redis.hget(f"{self._prefix}:dlq", message_id))
                if message_id
                else None
            )
        except Exception as error:
            raise QueueInfrastructureError("Redis DLQ task lookup failed") from error
        return DeadLetterRecord.model_validate_json(raw) if raw else None

    async def list(self, offset: int = 0, limit: int = 100) -> list[DeadLetterRecord]:
        if offset < 0 or not 1 <= limit <= 500:
            raise ValueError("Invalid DLQ pagination")
        try:
            records = await cast(Any, self._redis.hvals(f"{self._prefix}:dlq"))
        except Exception as error:
            raise QueueInfrastructureError("Redis DLQ listing failed") from error
        parsed = sorted(
            (DeadLetterRecord.model_validate_json(item) for item in records),
            key=lambda item: (item.created_at, item.id),
        )
        return parsed[offset : offset + limit]

    async def count(self) -> int:
        try:
            return int(await cast(Any, self._redis.hlen(f"{self._prefix}:dlq")))
        except Exception as error:
            raise QueueInfrastructureError("Redis DLQ count failed") from error

    async def approve_replay(self, record_id: str, approved: bool) -> DeadLetterRecord | None:
        record = await self.get(record_id)
        if record is None:
            return None
        updated = record.model_copy(
            update={
                "approval_status": (
                    ReplayApproval.APPROVED if approved else ReplayApproval.DENIED
                )
            }
        )
        try:
            await cast(
                Any,
                self._redis.hset(
                    f"{self._prefix}:dlq", updated.message_id, updated.model_dump_json()
                ),
            )
        except Exception as error:
            raise QueueInfrastructureError("Redis DLQ approval failed") from error
        return updated

    async def replay(self, record_id: str) -> tuple[ReplayResult, str | None]:
        record = await self.get(record_id)
        if record is None:
            return ReplayResult.NOT_FOUND, None
        new_message_id = str(uuid4())
        ready = [f"{self._prefix}:ready:{priority}" for priority in range(4)]
        try:
            result = await cast(
                Any,
                self._redis.eval(
                    _REPLAY_SCRIPT,
                    3 + len(ready),
                    f"{self._prefix}:dlq",
                    f"{self._prefix}:cancelled",
                    "unused",
                    *ready,
                    record.message_id,
                    new_message_id,
                    datetime.now(UTC).isoformat(),
                ),
            )
        except Exception as error:
            raise QueueInfrastructureError("Redis DLQ replay failed") from error
        if int(result[0]):
            return ReplayResult.REPLAYED, str(result[1])
        return ReplayResult(str(result[1])), None
