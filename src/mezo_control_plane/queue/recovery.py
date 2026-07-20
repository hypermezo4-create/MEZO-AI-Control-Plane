import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from redis.asyncio import Redis

from mezo_control_plane.queue.dead_letter_queue import DeadLetterRecord, ReplayApproval
from mezo_control_plane.queue.producer import QueueInfrastructureError
from mezo_control_plane.queue.retry_policy import RetryPolicy
from mezo_control_plane.queue.retry_scheduler import RetryRecord

_RECOVER_ONE_SCRIPT = """
local score=redis.call('ZSCORE', KEYS[3], ARGV[1])
if not score then return 'missing-index' end
if tonumber(score) > tonumber(ARGV[2]) then return 'renewed' end
local lease=redis.call('HGET', KEYS[2], ARGV[1])
local item=redis.call('HGET', KEYS[1], ARGV[1])
if not lease or not item then
  redis.call('HDEL', KEYS[1], ARGV[1]); redis.call('HDEL', KEYS[2], ARGV[1])
  redis.call('ZREM', KEYS[3], ARGV[1]); return 'orphan-cleaned'
end
local metadata=cjson.decode(lease)
if tonumber(metadata.lease_deadline) > tonumber(ARGV[2]) then return 'renewed' end
local envelope=cjson.decode(item)
local task=cjson.decode(envelope.task_json)
local terminal=ARGV[3] == '1' or task.state == 'completed' or task.state == 'failed'
local cancelled=redis.call('SISMEMBER', KEYS[4], envelope.task_id) == 1 or task.state == 'cancelled'
redis.call('HDEL', KEYS[1], ARGV[1]); redis.call('HDEL', KEYS[2], ARGV[1])
redis.call('ZREM', KEYS[3], ARGV[1])
if terminal then return 'terminal-cleaned' end
if cancelled then return 'cancelled-cleaned' end
if ARGV[4] == 'dlq' then
  redis.call('HSETNX', KEYS[7], ARGV[1], ARGV[5])
  redis.call('HSET', KEYS[8], envelope.task_id, ARGV[1])
  redis.call('HINCRBY', KEYS[9], 'dlq_finalizations', 1)
  redis.call('HINCRBY', KEYS[9], 'recoveries', 1)
  return 'dead-lettered'
end
redis.call('HSETNX', KEYS[5], ARGV[1], ARGV[5])
redis.call('ZADD', KEYS[6], ARGV[6], ARGV[1])
redis.call('HINCRBY', KEYS[9], 'recoveries', 1)
redis.call('HINCRBY', KEYS[9], 'retry_schedules', 1)
return 'retry-scheduled'
"""

DurableStateReader = Callable[[str], Awaitable[str | None]]


@dataclass(frozen=True)
class RecoveryResult:
    candidates: int = 0
    retry_scheduled: int = 0
    dead_lettered: int = 0
    terminal_cleaned: int = 0
    cancelled_cleaned: int = 0
    orphan_cleaned: int = 0
    renewed: int = 0

    @property
    def recovered(self) -> int:
        return self.retry_scheduled + self.dead_lettered


class LeaseRecovery:
    def __init__(
        self,
        redis: Redis,
        prefix: str = "mezo:queue",
        durable_state: DurableStateReader | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._redis = redis
        self._prefix = prefix
        self._durable_state = durable_state
        self._policy = retry_policy or RetryPolicy()

    async def recover_expired(
        self,
        batch_size: int = 100,
        maximum_attempts: int | None = None,
        now: datetime | None = None,
    ) -> RecoveryResult:
        if batch_size < 1:
            raise ValueError("Recovery batch must be positive")
        current = now or datetime.now(UTC)
        try:
            candidates = await cast(
                Any,
                self._redis.zrangebyscore(
                    f"{self._prefix}:lease-expiry",
                    "-inf",
                    current.timestamp(),
                    start=0,
                    num=batch_size,
                ),
            )
        except Exception as error:
            raise QueueInfrastructureError("Redis lease recovery discovery failed") from error
        counts: dict[str, int] = {}
        for candidate in candidates:
            status = await self._recover_one(
                str(candidate), current, maximum_attempts or self._policy.maximum_attempts
            )
            counts[status] = counts.get(status, 0) + 1
        return RecoveryResult(
            candidates=len(candidates),
            retry_scheduled=counts.get("retry-scheduled", 0),
            dead_lettered=counts.get("dead-lettered", 0),
            terminal_cleaned=counts.get("terminal-cleaned", 0),
            cancelled_cleaned=counts.get("cancelled-cleaned", 0),
            orphan_cleaned=counts.get("orphan-cleaned", 0),
            renewed=counts.get("renewed", 0),
        )

    async def _recover_one(self, message_id: str, now: datetime, maximum_attempts: int) -> str:
        try:
            envelope_raw = await cast(
                Any, self._redis.hget(f"{self._prefix}:inflight", message_id)
            )
            lease_raw = await cast(
                Any, self._redis.hget(f"{self._prefix}:leases", message_id)
            )
        except Exception as error:
            raise QueueInfrastructureError("Redis lease recovery lookup failed") from error
        envelope = json.loads(envelope_raw) if envelope_raw else None
        lease = json.loads(lease_raw) if lease_raw else None
        task_id = str(envelope["task_id"]) if envelope else ""
        durable_state = (
            await self._durable_state(task_id) if self._durable_state and task_id else None
        )
        terminal = durable_state in {"completed", "failed", "cancelled"}
        action = "retry"
        payload = "{}"
        due = now.timestamp()
        if envelope and lease:
            current_attempt = int(envelope.get("attempt", 0))
            first_failed = now
            decision = self._policy.decide(current_attempt + 1, True)
            exhausted = current_attempt + 1 >= maximum_attempts or not decision.retry
            history = [
                {
                    "attempt": current_attempt + 1,
                    "failure_class": "retryable_infrastructure",
                    "failed_at": now.isoformat(),
                    "summary": "lease expired before acknowledgement",
                    "previous_worker": lease.get("worker_id"),
                    "lease_deadline": lease.get("lease_deadline"),
                }
            ]
            updated = dict(envelope)
            updated["attempt"] = current_attempt + 1
            if exhausted:
                action = "dlq"
                payload = DeadLetterRecord(
                    message_id=message_id,
                    task_id=task_id,
                    envelope=updated,
                    priority=int(updated["priority"]),
                    attempts=current_attempt + 1,
                    failure_class="retry_exhaustion",
                    error_summary="lease expired and retry budget was exhausted",
                    worker_id=lease.get("worker_id"),
                    source_operation="recovery",
                    replay_eligible=True,
                    approval_status=ReplayApproval.PENDING,
                    attempt_history=history,
                ).model_dump_json()
            else:
                due = (now + timedelta(seconds=decision.delay_seconds)).timestamp()
                payload = RetryRecord(
                    message_id=message_id,
                    task_id=task_id,
                    envelope=updated,
                    priority=int(updated["priority"]),
                    attempt=current_attempt + 1,
                    due_at=datetime.fromtimestamp(due, UTC),
                    failure_class="retryable_infrastructure",
                    error_summary="lease expired before acknowledgement",
                    retry_after_source=decision.reason,
                    first_failed_at=first_failed,
                    latest_failed_at=now,
                    history=history,
                ).model_dump_json()
        keys = [
            f"{self._prefix}:inflight",
            f"{self._prefix}:leases",
            f"{self._prefix}:lease-expiry",
            f"{self._prefix}:cancelled",
            f"{self._prefix}:delayed",
            f"{self._prefix}:delayed-due",
            f"{self._prefix}:dlq",
            f"{self._prefix}:dlq-task-index",
            f"{self._prefix}:metric-counters",
        ]
        try:
            result = await cast(
                Any,
                self._redis.eval(
                    _RECOVER_ONE_SCRIPT,
                    len(keys),
                    *keys,
                    message_id,
                    str(now.timestamp()),
                    "1" if terminal else "0",
                    action,
                    payload,
                    str(due),
                ),
            )
        except Exception as error:
            raise QueueInfrastructureError("Redis lease recovery operation failed") from error
        return str(result)
