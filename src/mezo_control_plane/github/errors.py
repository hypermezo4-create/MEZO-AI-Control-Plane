from enum import StrEnum


class GitHubFailureType(StrEnum):
    AUTHENTICATION = "authentication"
    PERMISSION = "permission"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    VALIDATION = "validation"
    RATE_LIMIT = "rate_limit"
    SERVER = "server"
    NETWORK = "network"


class GitHubError(RuntimeError):
    def __init__(
        self,
        failure_type: GitHubFailureType,
        message: str,
        *,
        retryable: bool,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.failure_type = failure_type
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
