# ruff: noqa: E501
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from redis.asyncio import Redis

from mezo_control_plane.queue.priorities import TaskPriority
from mezo_control_plane.queue.producer import QueueInfrastructureError

_RECOVER_SCRIPT = """
local candidates=redis.call('ZRANGEBYSCORE', KEYS[3], '-inf', ARGV[1], 'LIMIT', 0, ARGV[2])
local recovered=0
for _,id in ipairs(candidates) do
  local lease=redis.call('HGET', KEYS[2], id)
  local item=redis.call('HGET', KEYS[1], id)
  if not lease or not item then
    redis.call('HDEL', KEYS[1], id); redis.call('HDEL', KEYS[2], id); redis.call('ZREM', KEYS[3], id)
  else
    local metadata=cjson.decode(lease)
    if tonumber(metadata.lease_deadline) <= tonumber(ARGV[1]) then
      local envelope=cjson.decode(item)
      local task=cjson.decode(envelope.task_json)
      redis.call('HDEL', KEYS[1], id); redis.call('HDEL', KEYS[2], id); redis.call('ZREM', KEYS[3], id)
      if redis.call('SISMEMBER', KEYS[4], envelope.task_id) == 0 and task.state ~= 'completed' and task.state ~= 'failed' and task.state ~= 'cancelled' then
        envelope.attempt=envelope.attempt+1
        if envelope.attempt >= tonumber(ARGV[3]) then
          redis.call('RPUSH', KEYS[5], cjson.encode({envelope=envelope, reason='lease-retry-exhausted'}))
        else
          redis.call('RPUSH', KEYS[7 + tonumber(envelope.priority)], cjson.encode(envelope))
        end
        recovered=recovered+1
      end
    end
  end
end
return recovered
"""


@dataclass(frozen=True)
class RecoveryResult:
    recovered: int


class LeaseRecovery:
    def __init__(self, redis: Redis, prefix: str = "mezo:queue") -> None:
        self._redis = redis
        self._prefix = prefix

    async def recover_expired(self, batch_size: int = 100, maximum_attempts: int = 5) -> RecoveryResult:
        if batch_size < 1 or maximum_attempts < 1:
            raise ValueError("Recovery batch and maximum attempts must be positive")
        keys = [
            f"{self._prefix}:inflight", f"{self._prefix}:leases", f"{self._prefix}:lease-expiry",
            f"{self._prefix}:cancelled", f"{self._prefix}:dlq",
            "unused",
            *(f"{self._prefix}:ready:{int(priority)}" for priority in TaskPriority),
        ]
        try:
            result = await cast(
                Any,
                self._redis.eval(
                    _RECOVER_SCRIPT, len(keys), *keys, str(datetime.now(UTC).timestamp()),
                    str(batch_size), str(maximum_attempts),
                ),
            )
        except Exception as error:
            raise QueueInfrastructureError("Redis lease recovery operation failed") from error
        return RecoveryResult(recovered=int(result))
