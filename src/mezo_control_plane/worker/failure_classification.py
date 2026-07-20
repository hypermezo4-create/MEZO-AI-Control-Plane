import asyncio
from dataclasses import dataclass
from enum import StrEnum


class FailureClass(StrEnum):
    RETRYABLE_PROVIDER = "retryable_provider"
    RETRYABLE_INFRASTRUCTURE = "retryable_infrastructure"
    RATE_LIMITED = "rate_limited"
    PERMANENT_VALIDATION = "permanent_validation"
    PERMANENT_AUTHORIZATION = "permanent_authorization"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    OWNERSHIP_LOST = "ownership_lost"


@dataclass(frozen=True)
class ExecutionFailure:
    classification: FailureClass
    summary: str
    retryable: bool
    retry_after_seconds: float | None = None


def classify_failure(error: BaseException) -> ExecutionFailure:
    if isinstance(error, TimeoutError):
        return ExecutionFailure(FailureClass.TIMEOUT, "execution deadline exceeded", True)
    if isinstance(error, PermissionError):
        return ExecutionFailure(FailureClass.PERMANENT_AUTHORIZATION, "authorization denied", False)
    if isinstance(error, ValueError):
        return ExecutionFailure(FailureClass.PERMANENT_VALIDATION, "validation failed", False)
    if isinstance(error, asyncio.CancelledError):
        return ExecutionFailure(FailureClass.CANCELLED, "execution cancelled", False)
    return ExecutionFailure(FailureClass.RETRYABLE_INFRASTRUCTURE, type(error).__name__, True)
