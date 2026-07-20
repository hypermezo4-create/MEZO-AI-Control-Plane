import random
from dataclasses import dataclass


@dataclass(frozen=True)
class RetryDecision:
    retry: bool
    delay_seconds: float


class RetryPolicy:
    def __init__(self, maximum_attempts: int = 5, base_delay_seconds: float = 1.0) -> None:
        self._maximum_attempts = maximum_attempts
        self._base_delay_seconds = base_delay_seconds

    def decide(
        self, attempt: int, retryable: bool, retry_after_seconds: float | None = None
    ) -> RetryDecision:
        if not retryable or attempt >= self._maximum_attempts:
            return RetryDecision(retry=False, delay_seconds=0)
        delay = retry_after_seconds or self._base_delay_seconds * (2 ** (attempt - 1))
        return RetryDecision(retry=True, delay_seconds=delay * random.uniform(0.8, 1.2))  # noqa: S311
