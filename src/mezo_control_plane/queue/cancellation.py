import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, cast

from pydantic import BaseModel
from redis.asyncio import Redis

from mezo_control_plane.queue.producer import QueueInfrastructureError

_CANCEL_SCRIPT = """
if redis.call('SISMEMBER', KEYS[1], ARGV[1]) == 1 then return 'already_cancelled' end
local message=redis.call('HGET', KEYS[3], ARGV[1])
local dlq=redis.call('HGET', KEYS[6], ARGV[1])
if not message and not dlq then return 'not_found' end
redis.call('SADD', KEYS[1], ARGV[1])
redis.call('HSET', KEYS[2], ARGV[1], ARGV[2])
redis.call('HINCRBY', KEYS[7], 'cancellations', 1)
if message then
  redis.call('HDEL', KEYS[4], message)
  redis.call('ZREM', KEYS[5], message)
end
return 'cancelled'
"""


class CancellationResult(StrEnum):
    CANCELLED = "cancelled"
    ALREADY_CANCELLED = "already_cancelled"
    ALREADY_TERMINAL = "already_terminal"
    NOT_FOUND = "not_found"
    RUNNING_TASK_SIGNALLED = "running_task_signalled"


class CancellationRecord(BaseModel):
    task_id: str
    actor: str
    reason: str
    cancelled_at: datetime
    evidence_reference: str | None = None


DurableCancellation = Callable[[str, str, str], Awaitable[CancellationResult]]


class CancellationService:
    def __init__(
        self,
        redis: Redis,
        prefix: str = "mezo:queue",
        durable_cancel: DurableCancellation | None = None,
    ) -> None:
        self._redis = redis
        self._prefix = prefix
        self._durable_cancel = durable_cancel
        self._local_signals: dict[str, asyncio.Event] = {}

    def register_running(self, task_id: str, signal: asyncio.Event) -> None:
        self._local_signals[task_id] = signal

    def unregister_running(self, task_id: str) -> None:
        self._local_signals.pop(task_id, None)

    async def cancel(
        self,
        task_id: str,
        actor: str = "system",
        reason: str = "cancelled by request",
        evidence_reference: str | None = None,
    ) -> CancellationResult:
        if self._durable_cancel is not None:
            durable = await self._durable_cancel(task_id, actor, reason)
            if durable in {CancellationResult.ALREADY_TERMINAL, CancellationResult.NOT_FOUND}:
                return durable
        record = CancellationRecord(
            task_id=task_id,
            actor=actor,
            reason=reason,
            cancelled_at=datetime.now(UTC),
            evidence_reference=evidence_reference,
        )
        try:
            result = await cast(
                Any,
                self._redis.eval(
                    _CANCEL_SCRIPT,
                    7,
                    f"{self._prefix}:cancelled",
                    f"{self._prefix}:cancellation-metadata",
                    f"{self._prefix}:task-index",
                    f"{self._prefix}:delayed",
                    f"{self._prefix}:delayed-due",
                    f"{self._prefix}:dlq-task-index",
                    f"{self._prefix}:metric-counters",
                    task_id,
                    record.model_dump_json(),
                ),
            )
        except Exception as error:
            raise QueueInfrastructureError("Redis cancellation operation failed") from error
        parsed = CancellationResult(str(result))
        signal = self._local_signals.get(task_id)
        if signal is not None and parsed in {
            CancellationResult.CANCELLED,
            CancellationResult.ALREADY_CANCELLED,
        }:
            signal.set()
            return CancellationResult.RUNNING_TASK_SIGNALLED
        return parsed

    async def is_cancelled(self, task_id: str) -> bool:
        try:
            member = await cast(Any, self._redis.sismember(f"{self._prefix}:cancelled", task_id))
            return bool(member)
        except Exception as error:
            raise QueueInfrastructureError("Redis cancellation lookup failed") from error

    async def get_record(self, task_id: str) -> CancellationRecord | None:
        try:
            raw = await cast(
                Any, self._redis.hget(f"{self._prefix}:cancellation-metadata", task_id)
            )
        except Exception as error:
            raise QueueInfrastructureError("Redis cancellation metadata lookup failed") from error
        return CancellationRecord.model_validate_json(raw) if raw else None
