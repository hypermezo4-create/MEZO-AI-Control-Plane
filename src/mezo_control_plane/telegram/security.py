import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from uuid import uuid4

from mezo_control_plane.telegram.models import TelegramRole


class CallbackValidationError(Exception):
    pass


@dataclass(frozen=True)
class TelegramAccessPolicy:
    allowed_users: frozenset[int]
    allowed_chats: frozenset[int]
    owners: frozenset[int]
    operators: frozenset[int]
    reviewers: frozenset[int]

    def role_for(self, user_id: int) -> TelegramRole | None:
        if user_id not in self.allowed_users:
            return None
        if user_id in self.owners:
            return TelegramRole.OWNER
        if user_id in self.operators:
            return TelegramRole.OPERATOR
        if user_id in self.reviewers:
            return TelegramRole.REVIEWER
        return TelegramRole.VIEWER


class CallbackSigner:
    def __init__(self, secret: str, lifetime_seconds: int = 300) -> None:
        if len(secret) < 16:
            raise ValueError("Telegram callback secret must contain at least 16 characters")
        self._secret = secret.encode()
        self._lifetime = lifetime_seconds
        self._used: dict[str, int] = {}

    def sign(self, action: str, task_id: str, now: int | None = None) -> str:
        payload = {
            "action": action,
            "task_id": task_id,
            "expires": (now or int(time.time())) + self._lifetime,
            "nonce": uuid4().hex[:12],
        }
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        encoded = base64.urlsafe_b64encode(raw).decode().rstrip("=")
        signature = hmac.new(self._secret, encoded.encode(), hashlib.sha256).hexdigest()[:32]
        return f"{encoded}.{signature}"

    def verify(self, token: str, now: int | None = None) -> dict[str, str]:
        try:
            encoded, supplied = token.split(".", 1)
            expected = hmac.new(self._secret, encoded.encode(), hashlib.sha256).hexdigest()[:32]
            if not hmac.compare_digest(supplied, expected):
                raise CallbackValidationError("Callback signature is invalid")
            padding = "=" * (-len(encoded) % 4)
            payload = json.loads(base64.urlsafe_b64decode(encoded + padding))
        except (ValueError, json.JSONDecodeError) as error:
            raise CallbackValidationError("Callback payload is malformed") from error
        if int(payload["expires"]) < (now or int(time.time())):
            raise CallbackValidationError("Callback has expired")
        nonce = str(payload["nonce"])
        current = now or int(time.time())
        self._used = {key: expiry for key, expiry in self._used.items() if expiry >= current}
        if nonce in self._used:
            raise CallbackValidationError("Callback was already used")
        self._used[nonce] = int(payload["expires"])
        return {"action": str(payload["action"]), "task_id": str(payload["task_id"])}
