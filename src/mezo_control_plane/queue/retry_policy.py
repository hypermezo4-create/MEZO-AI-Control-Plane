import random
from dataclasses import dataclass


@dataclass(frozen=True)
class RetryDecision:
    retry: bool
    delay_seconds: float
    reason: str


class RetryPolicy:
    def __init__(
        self,
        maximum_attempts: int = 5,
        base_delay_seconds: float = 1.0,
        maximum_delay_seconds: float = 300,
        maximum_elapsed_seconds: float = 3600,
        jitter_ratio: float = 0.2,
        random_source: random.Random | None = None,
    ) -> None:
        if maximum_attempts < 1 or base_delay_seconds <= 0 or maximum_elapsed_seconds <= 0:
            raise ValueError("Retry limits must be positive")
        if not 0 <= jitter_ratio <= 1:
            raise ValueError("Retry jitter ratio must be between zero and one")
        self.maximum_attempts = maximum_attempts
        self._base_delay = base_delay_seconds
        self._maximum_delay = maximum_delay_seconds
        self._maximum_elapsed = maximum_elapsed_seconds
        self._jitter_ratio = jitter_ratio
        self._random = random_source or random.SystemRandom()

    def decide(
        self,
        attempt: int,
        retryable: bool,
        retry_after_seconds: float | None = None,
        elapsed_seconds: float = 0,
    ) -> RetryDecision:
        if not retryable:
            return RetryDecision(False, 0, "permanent-failure")
        if attempt >= self.maximum_attempts:
            return RetryDecision(False, 0, "attempt-budget-exhausted")
        if elapsed_seconds >= self._maximum_elapsed:
            return RetryDecision(False, 0, "elapsed-time-budget-exhausted")
        if retry_after_seconds is not None:
            delay = max(0, retry_after_seconds)
            reason = "retry-after"
        else:
            calculated = min(self._maximum_delay, self._base_delay * (2 ** max(0, attempt - 1)))
            spread = calculated * self._jitter_ratio
            delay = self._random.uniform(calculated - spread, calculated + spread)
            reason = "exponential-backoff"
        if elapsed_seconds + delay > self._maximum_elapsed:
            return RetryDecision(False, 0, "elapsed-time-budget-exhausted")
        return RetryDecision(True, delay, reason)
