import json
from dataclasses import dataclass
from typing import Any, cast
from uuid import uuid4

from redis.asyncio import Redis

from mezo_control_plane.core.domain import TaskRecord, TaskState
from mezo_control_plane.queue.priorities import TaskPriority

_CLAIM_SCRIPT = """
for i=1,#KEYS do
  local item=redis.call('LPOP', KEYS[i])
  if item then
    local decoded=cjson.decode(item)
    decoded.owner_token=ARGV[1]
    local claimed=cjson.encode(decoded)
    redis.call('HSET', KEYS[#KEYS], decoded.message_id, claimed)
    return claimed
  end
end
return false
"""
_ACK_SCRIPT = """
if redis.call('HEXISTS', KEYS[1], ARGV[1]) == 1 then
  local payload=redis.call('HGET', KEYS[1], ARGV[1])
  local decoded=cjson.decode(payload)
  if decoded.owner_token == ARGV[2] then redis.call('HDEL', KEYS[1], ARGV[1]); return 1 end
end
return 0
"""
_RENEW_SCRIPT = """
local payload=redis.call('HGET', KEYS[1], ARGV[1])
if not payload then return 0 end
local decoded=cjson.decode(payload)
if decoded.owner_token ~= ARGV[2] then return 0 end
return redis.call('EXPIRE', KEYS[2], ARGV[3])
"""


@dataclass(frozen=True)
class ClaimedTask:
    task: TaskRecord
    message_id: str
    owner_token: str
    attempt: int


class TaskConsumer:
    def __init__(self, redis: Redis, worker_id: str) -> None:
        self._redis = redis
        self._worker_id = worker_id

    async def claim(self) -> ClaimedTask | None:
        owner_token = f"{self._worker_id}:{uuid4()}"
        keys = [*(f"mezo:queue:ready:{int(item)}" for item in TaskPriority), "mezo:queue:inflight"]
        raw = await cast(Any, self._redis.eval(_CLAIM_SCRIPT, len(keys), *keys, owner_token))
        if raw is None:
            return None
        envelope = json.loads(raw)
        await cast(
            Any, self._redis.expire(f"mezo:queue:lease:{envelope['message_id']}", 60)
        )
        task = TaskRecord.model_validate(envelope["task"])
        if task.state in {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}:
            await cast(Any, self._redis.hdel("mezo:queue:inflight", envelope["message_id"]))
            return None
        return ClaimedTask(task, envelope["message_id"], owner_token, int(envelope["attempt"]))

    async def acknowledge(self, claimed: ClaimedTask) -> bool:
        result = await cast(
            Any,
            self._redis.eval(
                _ACK_SCRIPT, 1, "mezo:queue:inflight", claimed.message_id, claimed.owner_token
            ),
        )
        return bool(result)

    async def renew_lease(self, claimed: ClaimedTask, visibility_seconds: int = 60) -> bool:
        if visibility_seconds < 1:
            raise ValueError("Visibility timeout must be positive")
        result = await cast(
            Any,
            self._redis.eval(
                _RENEW_SCRIPT,
                2,
                "mezo:queue:inflight",
                f"mezo:queue:lease:{claimed.message_id}",
                claimed.message_id,
                claimed.owner_token,
                str(visibility_seconds),
            ),
        )
        return bool(result)
