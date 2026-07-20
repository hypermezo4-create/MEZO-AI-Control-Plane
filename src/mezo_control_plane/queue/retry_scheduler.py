import json
from datetime import UTC, datetime
from typing import Any, cast

from redis.asyncio import Redis

from mezo_control_plane.queue.priorities import TaskPriority
from mezo_control_plane.queue.producer import QueueInfrastructureError

_PROMOTE_SCRIPT = """
local ids=redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[1], 'LIMIT', 0, ARGV[2])
local count=0
for _,id in ipairs(ids) do
  local item=redis.call('HGET', KEYS[2], id)
  if item then
    local envelope=cjson.decode(item)
    redis.call('HDEL', KEYS[2], id); redis.call('ZREM', KEYS[1], id)
    if redis.call('SISMEMBER', KEYS[3], envelope.task_id) == 0 then
      redis.call('RPUSH', KEYS[4 + tonumber(envelope.priority)], item); count=count+1
    end
  else redis.call('ZREM', KEYS[1], id) end
end
return count
"""


class RetryScheduler:
    def __init__(self, redis: Redis, prefix: str = "mezo:queue") -> None:
        self._redis = redis
        self._prefix = prefix

    async def schedule(self, envelope: dict[str, object], due_at: datetime) -> None:
        message_id = str(envelope["message_id"])
        try:
            await cast(
                Any, self._redis.hset(f"{self._prefix}:delayed", message_id, json.dumps(envelope))
            )
            await cast(
                Any,
                self._redis.zadd(
                    f"{self._prefix}:delayed-due", {message_id: due_at.timestamp()}
                ),
            )
        except Exception as error:
            raise QueueInfrastructureError("Redis retry scheduling failed") from error

    async def promote_due(self, batch_size: int = 100) -> int:
        keys = [
            f"{self._prefix}:delayed-due", f"{self._prefix}:delayed", f"{self._prefix}:cancelled",
            *(f"{self._prefix}:ready:{int(priority)}" for priority in TaskPriority),
        ]
        try:
            result = await cast(
                Any,
                self._redis.eval(
                    _PROMOTE_SCRIPT,
                    len(keys),
                    *keys,
                    str(datetime.now(UTC).timestamp()),
                    str(batch_size),
                ),
            )
            return int(result)
        except Exception as error:
            raise QueueInfrastructureError("Redis retry promotion failed") from error
