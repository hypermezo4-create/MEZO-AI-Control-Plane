import json
from typing import Any, cast

from redis.asyncio import Redis


class DeadLetterQueue:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def put(self, payload: dict[str, Any], reason: str) -> None:
        message = json.dumps({"payload": payload, "reason": reason})
        await cast(Any, self._redis.rpush("mezo:queue:dlq", message))

    async def depth(self) -> int:
        return int(await cast(Any, self._redis.llen("mezo:queue:dlq")))
