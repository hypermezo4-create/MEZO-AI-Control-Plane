from datetime import UTC, datetime, timedelta
from typing import Any, cast

from pydantic import BaseModel, Field
from redis.asyncio import Redis

from mezo_control_plane.queue.priorities import TaskPriority
from mezo_control_plane.queue.producer import QueueInfrastructureError
from mezo_control_plane.queue.retry_policy import RetryPolicy
from mezo_control_plane.worker.failure_classification import ExecutionFailure

_SCHEDULE_SCRIPT = """
if redis.call('SISMEMBER', KEYS[3], ARGV[2]) == 1 then return 0 end
if redis.call('HEXISTS', KEYS[2], ARGV[1]) == 1 then return 0 end
redis.call('HSET', KEYS[2], ARGV[1], ARGV[3])
redis.call('ZADD', KEYS[1], ARGV[4], ARGV[1])
return 1
"""
_PROMOTE_SCRIPT = """
local ids=redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[1], 'LIMIT', 0, ARGV[2])
local promoted=0
local cancelled=0
local terminal=0
for _,id in ipairs(ids) do
  local raw=redis.call('HGET', KEYS[2], id)
  if not raw then
    redis.call('ZREM', KEYS[1], id)
  else
    local retry=cjson.decode(raw)
    local envelope=retry.envelope
    local task=cjson.decode(envelope.task_json)
    if redis.call('SISMEMBER', KEYS[3], retry.task_id) == 1 then
      redis.call('HDEL', KEYS[2], id); redis.call('ZREM', KEYS[1], id); cancelled=cancelled+1
    elseif task.state == 'completed' or task.state == 'failed' or task.state == 'cancelled' then
      redis.call('HDEL', KEYS[2], id); redis.call('ZREM', KEYS[1], id); terminal=terminal+1
    else
      redis.call('HDEL', KEYS[2], id); redis.call('ZREM', KEYS[1], id)
      redis.call('RPUSH', KEYS[4 + tonumber(envelope.priority)], cjson.encode(envelope))
      promoted=promoted+1
    end
  end
end
return {promoted,cancelled,terminal}
"""


class RetryRecord(BaseModel):
    message_id: str
    task_id: str
    envelope: dict[str, object]
    priority: int
    attempt: int = Field(ge=1)
    due_at: datetime
    failure_class: str
    error_summary: str = Field(max_length=1_000)
    retry_after_source: str
    first_failed_at: datetime
    latest_failed_at: datetime
    evidence_reference: str | None = None
    history: list[dict[str, object]] = Field(default_factory=list)


class RetryScheduleResult(BaseModel):
    scheduled: bool
    exhausted: bool
    record: RetryRecord | None = None


class RetryPromotionResult(BaseModel):
    promoted: int
    cancelled: int
    terminal: int


class RetryScheduler:
    def __init__(
        self,
        redis: Redis,
        prefix: str = "mezo:queue",
        policy: RetryPolicy | None = None,
    ) -> None:
        self._redis = redis
        self._prefix = prefix
        self._policy = policy or RetryPolicy()

    async def schedule_failure(
        self,
        envelope: dict[str, object],
        failure: ExecutionFailure,
        *,
        now: datetime | None = None,
        first_failed_at: datetime | None = None,
        history: list[dict[str, object]] | None = None,
        evidence_reference: str | None = None,
    ) -> RetryScheduleResult:
        current = now or datetime.now(UTC)
        first = first_failed_at or current
        attempt = int(str(envelope.get("attempt", 0))) + 1
        decision = self._policy.decide(
            attempt,
            failure.retryable,
            failure.retry_after_seconds,
            (current - first).total_seconds(),
        )
        if not decision.retry:
            return RetryScheduleResult(scheduled=False, exhausted=True)
        updated = dict(envelope)
        updated["attempt"] = attempt
        due_at = current + timedelta(seconds=decision.delay_seconds)
        attempt_history = list(history or [])
        attempt_history.append(
            {
                "attempt": attempt,
                "failure_class": failure.classification.value,
                "failed_at": current.isoformat(),
                "summary": failure.summary,
            }
        )
        record = RetryRecord(
            message_id=str(updated["message_id"]),
            task_id=str(updated["task_id"]),
            envelope=updated,
            priority=int(str(updated["priority"])),
            attempt=attempt,
            due_at=due_at,
            failure_class=failure.classification.value,
            error_summary=failure.summary,
            retry_after_source=decision.reason,
            first_failed_at=first,
            latest_failed_at=current,
            evidence_reference=evidence_reference,
            history=attempt_history,
        )
        try:
            scheduled = await cast(
                Any,
                self._redis.eval(
                    _SCHEDULE_SCRIPT,
                    3,
                    f"{self._prefix}:delayed-due",
                    f"{self._prefix}:delayed",
                    f"{self._prefix}:cancelled",
                    record.message_id,
                    record.task_id,
                    record.model_dump_json(),
                    str(due_at.timestamp()),
                ),
            )
        except Exception as error:
            raise QueueInfrastructureError("Redis retry scheduling failed") from error
        return RetryScheduleResult(scheduled=bool(scheduled), exhausted=False, record=record)

    async def promote_due(
        self, batch_size: int = 100, now: datetime | None = None
    ) -> RetryPromotionResult:
        if batch_size < 1:
            raise ValueError("Retry promotion batch must be positive")
        keys = [
            f"{self._prefix}:delayed-due",
            f"{self._prefix}:delayed",
            f"{self._prefix}:cancelled",
            *(f"{self._prefix}:ready:{int(priority)}" for priority in TaskPriority),
        ]
        try:
            result = await cast(
                Any,
                self._redis.eval(
                    _PROMOTE_SCRIPT,
                    len(keys),
                    *keys,
                    str((now or datetime.now(UTC)).timestamp()),
                    str(batch_size),
                ),
            )
        except Exception as error:
            raise QueueInfrastructureError("Redis retry promotion failed") from error
        return RetryPromotionResult(
            promoted=int(result[0]), cancelled=int(result[1]), terminal=int(result[2])
        )

    async def get(self, message_id: str) -> RetryRecord | None:
        try:
            raw = await cast(Any, self._redis.hget(f"{self._prefix}:delayed", message_id))
        except Exception as error:
            raise QueueInfrastructureError("Redis retry lookup failed") from error
        return RetryRecord.model_validate_json(raw) if raw else None
