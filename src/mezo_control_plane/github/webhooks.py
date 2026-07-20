from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass
from typing import Any

ALLOWED_EVENTS = frozenset(
    {
        "push",
        "pull_request",
        "pull_request_review",
        "check_run",
        "check_suite",
        "issue",
        "issues",
        "issue_comment",
        "installation",
        "installation_repositories",
    }
)


@dataclass(frozen=True)
class WebhookEvent:
    delivery_id: str
    event: str
    installation_id: int | None
    repository: str | None
    payload: dict[str, Any]
    actionable: bool


class WebhookReplayStore:
    def __init__(self, ttl_seconds: int = 3600) -> None:
        self._ttl = ttl_seconds
        self._seen: dict[str, float] = {}

    def claim(self, delivery_id: str, now: float | None = None) -> bool:
        current = now if now is not None else time.time()
        self._seen = {key: expiry for key, expiry in self._seen.items() if expiry > current}
        if delivery_id in self._seen:
            return False
        self._seen[delivery_id] = current + self._ttl
        return True


class WebhookVerifier:
    def __init__(
        self,
        secret: str,
        replay_store: WebhookReplayStore,
        *,
        allowed_repositories: frozenset[str],
        max_body_bytes: int = 1_000_000,
    ) -> None:
        self._secret = secret.encode()
        self._replay = replay_store
        self._repositories = allowed_repositories
        self._max_body = max_body_bytes

    def verify(self, body: bytes, signature: str, delivery_id: str, event: str) -> WebhookEvent:
        if len(body) > self._max_body:
            raise ValueError("Webhook body exceeds limit")
        if not re.fullmatch(r"[A-Za-z0-9-]{1,128}", delivery_id):
            raise ValueError("Invalid delivery ID")
        expected = "sha256=" + hmac.new(self._secret, body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise PermissionError("Invalid webhook signature")
        if not self._replay.claim(delivery_id):
            raise FileExistsError("Webhook delivery already processed")
        payload = json.loads(body)
        repository = payload.get("repository", {}).get("full_name")
        installation = payload.get("installation", {}).get("id")
        if repository is not None and repository not in self._repositories:
            raise PermissionError("Webhook repository is not allowlisted")
        return WebhookEvent(
            delivery_id,
            event,
            int(installation) if installation is not None else None,
            repository,
            payload,
            event in ALLOWED_EVENTS,
        )
