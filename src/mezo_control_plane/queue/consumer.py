# ruff: noqa: E501
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from redis.asyncio import Redis

from mezo_control_plane.core.domain import TaskRecord
from mezo_control_plane.queue.priorities import TaskPriority
from mezo_control_plane.queue.producer import QueueInfrastructureError

_READY_COUNT = len(TaskPriority)
_CLAIM_SCRIPT = """
for i=1,ARGV[1] do
  local item=redis.call('LPOP', KEYS[i])
  if item then
    local envelope=cjson.decode(item)
    local task=cjson.decode(envelope.task_json)
    if redis.call('SISMEMBER', KEYS[8], envelope.task_id) == 1 or task.state == 'completed' or task.state == 'failed' or task.state == 'cancelled' then
      redis.call('HDEL', KEYS[5], envelope.message_id)
      redis.call('HDEL', KEYS[6], envelope.message_id)
      redis.call('ZREM', KEYS[7], envelope.message_id)
    else
      envelope.owner_token=ARGV[2]
      envelope.worker_id=ARGV[3]
      envelope.claimed_at=ARGV[4]
      envelope.lease_expires_at=ARGV[5]
      local encoded=cjson.encode(envelope)
      local lease=cjson.encode({message_id=envelope.message_id,task_id=envelope.task_id,
        worker_id=ARGV[3],owner_token=ARGV[2],claimed_at=ARGV[4],
        lease_expires_at=ARGV[5],lease_deadline=ARGV[6],attempt=envelope.attempt})
      redis.call('HSET', KEYS[5], envelope.message_id, encoded)
      redis.call('HSET', KEYS[6], envelope.message_id, lease)
      redis.call('ZADD', KEYS[7], ARGV[6], envelope.message_id)
      redis.call('HINCRBY', KEYS[9], 'claims', 1)
      return encoded
    end
  end
end
return false
"""
_ACK_SCRIPT = """
local lease=redis.call('HGET', KEYS[2], ARGV[1])
if not lease then return 0 end
local metadata=cjson.decode(lease)
if metadata.owner_token ~= ARGV[2] then return -1 end
if redis.call('SISMEMBER', KEYS[4], metadata.task_id) == 1 then return -2 end
redis.call('HDEL', KEYS[1], ARGV[1])
redis.call('HDEL', KEYS[2], ARGV[1])
redis.call('ZREM', KEYS[3], ARGV[1])
redis.call('HINCRBY', KEYS[5], 'acknowledgements', 1)
return 1
"""
_RENEW_SCRIPT = """
local lease=redis.call('HGET', KEYS[2], ARGV[1])
if not lease or redis.call('SISMEMBER', KEYS[4], ARGV[3]) == 1 then return 0 end
local metadata=cjson.decode(lease)
if metadata.owner_token ~= ARGV[2] then return -1 end
metadata.lease_expires_at=ARGV[4]
metadata.lease_deadline=ARGV[5]
redis.call('HSET', KEYS[2], ARGV[1], cjson.encode(metadata))
redis.call('ZADD', KEYS[3], ARGV[5], ARGV[1])
redis.call('HINCRBY', KEYS[5], 'renewals', 1)
return 1
"""


@dataclass(frozen=True)
class ClaimedTask:
    task: TaskRecord
    message_id: str
    owner_token: str
    attempt: int
    lease_expires_at: datetime


class TaskConsumer:
    def __init__(self, redis: Redis, worker_id: str, prefix: str = "mezo:queue") -> None:
        self._redis = redis
        self._worker_id = worker_id
        self._prefix = prefix

    async def claim(self, visibility_seconds: int = 60) -> ClaimedTask | None:
        now = datetime.now(UTC)
        expiry = now.timestamp() + visibility_seconds
        owner_token = f"{self._worker_id}:{uuid4()}"
        ready = [f"{self._prefix}:ready:{int(priority)}" for priority in TaskPriority]
        keys = [
            *ready,
            f"{self._prefix}:inflight",
            f"{self._prefix}:leases",
            f"{self._prefix}:lease-expiry",
            f"{self._prefix}:cancelled",
            f"{self._prefix}:metric-counters",
        ]
        try:
            raw = await cast(
                Any,
                self._redis.eval(
                    _CLAIM_SCRIPT,
                    len(keys),
                    *keys,
                    str(_READY_COUNT),
                    owner_token,
                    self._worker_id,
                    now.isoformat(),
                    datetime.fromtimestamp(expiry, UTC).isoformat(),
                    str(expiry),
                ),
            )
        except Exception as error:
            raise QueueInfrastructureError("Redis claim operation failed") from error
        if not raw:
            return None
        envelope = json.loads(raw)
        task = TaskRecord.model_validate_json(envelope["task_json"])
        return ClaimedTask(
            task=task,
            message_id=envelope["message_id"],
            owner_token=owner_token,
            attempt=int(envelope["attempt"]),
            lease_expires_at=datetime.fromisoformat(envelope["lease_expires_at"]),
        )

    async def acknowledge(self, claimed: ClaimedTask) -> bool:
        if not claimed.owner_token.startswith(f"{self._worker_id}:"):
            return False
        try:
            result = await cast(
                Any,
                self._redis.eval(
                    _ACK_SCRIPT,
                    5,
                    f"{self._prefix}:inflight",
                    f"{self._prefix}:leases",
                    f"{self._prefix}:lease-expiry",
                    f"{self._prefix}:cancelled",
                    f"{self._prefix}:metric-counters",
                    claimed.message_id,
                    claimed.owner_token,
                ),
            )
        except Exception as error:
            raise QueueInfrastructureError("Redis acknowledgement operation failed") from error
        return int(result) == 1

    async def renew_lease(self, claimed: ClaimedTask, visibility_seconds: int = 60) -> bool:
        if not claimed.owner_token.startswith(f"{self._worker_id}:"):
            return False
        expiry = datetime.now(UTC).timestamp() + visibility_seconds
        try:
            result = await cast(
                Any,
                self._redis.eval(
                    _RENEW_SCRIPT,
                    5,
                    f"{self._prefix}:inflight",
                    f"{self._prefix}:leases",
                    f"{self._prefix}:lease-expiry",
                    f"{self._prefix}:cancelled",
                    f"{self._prefix}:metric-counters",
                    claimed.message_id,
                    claimed.owner_token,
                    str(claimed.task.id),
                    datetime.fromtimestamp(expiry, UTC).isoformat(),
                    str(expiry),
                ),
            )
        except Exception as error:
            raise QueueInfrastructureError("Redis lease renewal operation failed") from error
        return int(result) == 1
