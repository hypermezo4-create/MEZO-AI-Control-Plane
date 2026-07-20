from __future__ import annotations

import asyncio
import base64
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from mezo_control_plane.github.errors import GitHubError, GitHubFailureType


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


class GitHubAppJWT:
    def __init__(self, app_id: str, private_key_pem: str) -> None:
        self._app_id = app_id
        try:
            key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
        except (TypeError, ValueError) as error:
            raise GitHubError(
                GitHubFailureType.AUTHENTICATION,
                "GitHub App private key is invalid",
                retryable=False,
            ) from error
        if not isinstance(key, rsa.RSAPrivateKey):
            raise GitHubError(
                GitHubFailureType.AUTHENTICATION,
                "GitHub App key must be RSA",
                retryable=False,
            )
        self._key = key

    def create(self, now: int | None = None) -> str:
        issued = now if now is not None else int(time.time())
        header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
        payload = _b64url(
            json.dumps({"iat": issued - 60, "exp": issued + 540, "iss": self._app_id}).encode()
        )
        signing_input = f"{header}.{payload}".encode()
        signature = self._key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        return f"{header}.{payload}.{_b64url(signature)}"


@dataclass(frozen=True)
class InstallationToken:
    value: str
    expires_at: datetime
    permissions: frozenset[str]

    def usable(self, now: datetime, early_refresh_seconds: int) -> bool:
        return (self.expires_at - now).total_seconds() > early_refresh_seconds


TokenExchange = Callable[[int], Awaitable[InstallationToken]]


class InstallationTokenCache:
    def __init__(self, exchange: TokenExchange, early_refresh_seconds: int = 300) -> None:
        self._exchange = exchange
        self._early_refresh = early_refresh_seconds
        self._tokens: dict[int, InstallationToken] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    async def get(self, installation_id: int) -> InstallationToken:
        now = datetime.now(UTC)
        cached = self._tokens.get(installation_id)
        if cached and cached.usable(now, self._early_refresh):
            return cached
        lock = self._locks.setdefault(installation_id, asyncio.Lock())
        async with lock:
            cached = self._tokens.get(installation_id)
            if cached and cached.usable(datetime.now(UTC), self._early_refresh):
                return cached
            token = await self._exchange(installation_id)
            self._tokens[installation_id] = token
            return token

    def invalidate(self, installation_id: int) -> None:
        self._tokens.pop(installation_id, None)


class AppAuthTransport(Protocol):
    async def request(
        self, method: str, path: str, *, token: str, json_body: dict[str, Any] | None = None
    ) -> tuple[int, dict[str, Any], dict[str, str]]: ...


class InstallationService:
    def __init__(self, transport: AppAuthTransport, app_jwt: GitHubAppJWT) -> None:
        self._transport = transport
        self._jwt = app_jwt

    async def discover(self, repository: str) -> int:
        status, payload, _ = await self._transport.request(
            "GET", f"/repos/{repository}/installation", token=self._jwt.create()
        )
        if status != 200 or "id" not in payload:
            raise GitHubError(
                GitHubFailureType.PERMISSION,
                "GitHub App installation was not found for repository",
                retryable=False,
            )
        return int(payload["id"])

    async def exchange(self, installation_id: int) -> InstallationToken:
        status, payload, _ = await self._transport.request(
            "POST",
            f"/app/installations/{installation_id}/access_tokens",
            token=self._jwt.create(),
            json_body={},
        )
        if status != 201:
            raise GitHubError(
                GitHubFailureType.AUTHENTICATION,
                "GitHub installation token exchange failed",
                retryable=status >= 500,
            )
        expires_at = datetime.fromisoformat(str(payload["expires_at"]).replace("Z", "+00:00"))
        permissions = frozenset(
            key for key, value in dict(payload.get("permissions", {})).items() if value != "none"
        )
        return InstallationToken(str(payload["token"]), expires_at, permissions)
