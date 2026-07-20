import asyncio
import base64
import json
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from mezo_control_plane.github.app_auth import (
    GitHubAppJWT,
    InstallationToken,
    InstallationTokenCache,
)
from mezo_control_plane.github.client import GitHubClient
from mezo_control_plane.github.errors import GitHubError, GitHubFailureType
from mezo_control_plane.github.webhooks import WebhookReplayStore, WebhookVerifier


def _private_key() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def test_jwt_claims_and_invalid_key() -> None:
    token = GitHubAppJWT("123", _private_key()).create(now=1_000)
    payload = token.split(".")[1] + "=="
    claims = json.loads(base64.urlsafe_b64decode(payload))
    assert claims == {"iat": 940, "exp": 1540, "iss": "123"}
    with pytest.raises(GitHubError, match="invalid"):
        GitHubAppJWT("123", "not a key")


@pytest.mark.asyncio
async def test_installation_token_cache_collapses_concurrent_refresh() -> None:
    calls = 0

    async def exchange(installation_id: int) -> InstallationToken:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return InstallationToken(
            f"token-{installation_id}", datetime.now(UTC) + timedelta(hours=1), frozenset()
        )

    cache = InstallationTokenCache(exchange)
    values = await asyncio.gather(*(cache.get(7) for _ in range(5)))
    assert calls == 1
    assert {value.value for value in values} == {"token-7"}


def test_webhook_signature_replay_and_unknown_event() -> None:
    import hashlib
    import hmac

    body = json.dumps(
        {"repository": {"full_name": "owner/repo"}, "installation": {"id": 9}}
    ).encode()
    signature = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    verifier = WebhookVerifier(
        "secret", WebhookReplayStore(), allowed_repositories=frozenset({"owner/repo"})
    )
    event = verifier.verify(body, signature, "delivery-1", "unknown")
    assert not event.actionable
    with pytest.raises(FileExistsError):
        verifier.verify(body, signature, "delivery-1", "push")
    with pytest.raises(PermissionError):
        WebhookVerifier(
            "wrong", WebhookReplayStore(), allowed_repositories=frozenset({"owner/repo"})
        ).verify(body, signature, "delivery-2", "push")


class FakeTransport:
    def __init__(self, responses: list[tuple[int, dict[str, object], dict[str, str]]]) -> None:
        self.responses = responses
        self.requests: list[tuple[str, str, dict[str, object] | None]] = []

    async def request(
        self,
        method: str,
        path: str,
        *,
        token: str,
        json_body: dict[str, object] | None = None,
    ) -> tuple[int, dict[str, object], dict[str, str]]:
        assert token
        self.requests.append((method, path, json_body))
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_branch_idempotency_and_draft_pr() -> None:
    transport = FakeTransport(
        [
            (422, {"message": "Reference already exists"}, {}),
            (201, {"number": 12, "html_url": "https://example.test/pr/12"}, {}),
        ]
    )
    client = GitHubClient(transport, allowed_repositories=frozenset({"owner/repo"}))
    branch = await client.create_branch("owner/repo", "a" * 40, "task", "Fix Thing", "x")
    assert branch == "agent/task-fix-thing"
    number, _ = await client.create_draft_pull_request(
        "owner/repo", "main", branch, "title", "evidence", "x"
    )
    assert number == 12


@pytest.mark.asyncio
async def test_base_movement_protected_paths_and_own_approval() -> None:
    transport = FakeTransport([(200, {"object": {"sha": "b" * 40}}, {})])
    client = GitHubClient(transport, allowed_repositories=frozenset({"owner/repo"}))
    with pytest.raises(GitHubError) as moved:
        await client.create_commit("owner/repo", "agent/t-x", "a" * 40, {"a.py": "x"}, "x")
    assert moved.value.failure_type is GitHubFailureType.CONFLICT
    with pytest.raises(GitHubError, match="cannot approve"):
        await client.approve_pull_request()


def test_permission_scope_denies_repository_branch_and_permission() -> None:
    client = GitHubClient(FakeTransport([]), allowed_repositories=frozenset({"owner/repo"}))
    assert not client.authorize(
        "other/repo", "agent/x", frozenset({"contents:write"}), "contents:write"
    ).allowed
    assert not client.authorize(
        "owner/repo", "main", frozenset({"contents:write"}), "contents:write"
    ).allowed
    assert not client.authorize("owner/repo", "agent/x", frozenset(), "contents:write").allowed
