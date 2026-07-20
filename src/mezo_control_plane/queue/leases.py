from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


@dataclass(frozen=True)
class Lease:
    task_id: str
    owner_token: str
    expires_at: datetime

    @classmethod
    def new(cls, task_id: str, owner_token: str, visibility_seconds: int) -> "Lease":
        return cls(task_id, owner_token, datetime.now(UTC) + timedelta(seconds=visibility_seconds))
