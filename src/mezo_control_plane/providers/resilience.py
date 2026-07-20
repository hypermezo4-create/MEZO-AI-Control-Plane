import time
from dataclasses import dataclass
from enum import StrEnum


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    failure_threshold: int = 3
    recovery_seconds: float = 30
    state: CircuitState = CircuitState.CLOSED
    failures: int = 0
    opened_at: float | None = None

    def allow(self, now: float | None = None) -> bool:
        current = now if now is not None else time.monotonic()
        if self.state is CircuitState.OPEN:
            if self.opened_at is not None and current - self.opened_at >= self.recovery_seconds:
                self.state = CircuitState.HALF_OPEN
                return True
            return False
        return True

    def success(self) -> None:
        self.state = CircuitState.CLOSED
        self.failures = 0
        self.opened_at = None

    def failure(self, now: float | None = None) -> None:
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self.state = CircuitState.OPEN
            self.opened_at = now if now is not None else time.monotonic()
