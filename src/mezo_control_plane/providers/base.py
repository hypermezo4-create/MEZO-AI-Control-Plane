import asyncio
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from mezo_control_plane.core.domain import ModelRequest, ModelResponse


class ProviderFailureType(StrEnum):
    AUTHENTICATION = "authentication"
    PERMISSION = "permission"
    QUOTA = "quota"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    CONNECTION = "connection"
    SERVER = "server"
    MALFORMED_OUTPUT = "malformed_output"
    CONTENT_POLICY = "content_policy"
    CANCELLATION = "cancellation"
    UNKNOWN_MODEL = "unknown_model"


class ProviderError(Exception):
    def __init__(
        self,
        failure_type: ProviderFailureType,
        message: str,
        *,
        retryable: bool,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.failure_type = failure_type
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


class ModelProvider(Protocol):
    name: str
    models: frozenset[str]

    async def generate(
        self,
        request: ModelRequest,
        model: str,
        *,
        deadline_seconds: float | None = None,
        cancellation: asyncio.Event | None = None,
    ) -> ModelResponse: ...

    async def healthy(self) -> bool: ...


@dataclass(frozen=True)
class ProviderHealth:
    provider: str
    healthy: bool
    circuit_state: str
    active_requests: int
    failures: int
    latency_seconds: float | None
