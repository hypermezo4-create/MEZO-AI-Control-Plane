import hashlib
import hmac
from collections.abc import AsyncIterator
from typing import cast
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr

from mezo_control_plane.api.main import create_app
from mezo_control_plane.application.ports import TaskStore
from mezo_control_plane.application.tasks import TaskApplicationService
from mezo_control_plane.core.domain import EvidenceItem, TaskRecord, TaskState
from mezo_control_plane.core.settings import Settings
from mezo_control_plane.queue.cancellation import CancellationResult, CancellationService
from mezo_control_plane.queue.producer import EnqueueResult, TaskProducer


class MemoryStore:
    def __init__(self) -> None:
        self.tasks: dict[UUID, TaskRecord] = {}
        self.keys: dict[str, UUID] = {}

    async def create(self, task: TaskRecord, idempotency_key: str) -> TaskRecord:
        existing = self.keys.get(idempotency_key)
        if existing:
            return self.tasks[existing]
        self.keys[idempotency_key] = task.id
        self.tasks[task.id] = task
        return task

    async def get(self, task_id: UUID) -> TaskRecord | None:
        return self.tasks.get(task_id)

    async def list_tasks(self, offset: int, limit: int) -> tuple[list[TaskRecord], int]:
        values = sorted(
            self.tasks.values(), key=lambda item: (item.created_at, item.id), reverse=True
        )
        return values[offset : offset + limit], len(values)

    async def transition(self, task_id: UUID, state: TaskState) -> TaskRecord:
        task = self.tasks[task_id].model_copy(update={"state": state})
        self.tasks[task_id] = task
        return task

    async def evidence(self, task_id: UUID) -> list[EvidenceItem]:
        return self.tasks[task_id].evidence_items


class MemoryProducer:
    def __init__(self) -> None:
        self.messages: dict[str, str] = {}

    async def enqueue(self, task: TaskRecord, key: str) -> EnqueueResult:
        accepted = key not in self.messages
        self.messages.setdefault(key, str(task.id))
        return EnqueueResult(message_id=self.messages[key], accepted=accepted)


class MemoryCancellation:
    async def cancel(self, task_id: str, actor: str, reason: str) -> CancellationResult:
        return CancellationResult.CANCELLED


async def healthy() -> bool:
    return True


@pytest.fixture
def api() -> tuple[TaskApplicationService, httpx.ASGITransport]:
    application = TaskApplicationService(
        cast(TaskStore, MemoryStore()),
        cast(TaskProducer, MemoryProducer()),
        cast(CancellationService, MemoryCancellation()),
        healthy,
        healthy,
        healthy,
    )
    settings = Settings(control_plane_api_key=SecretStr("test-control-key"))
    return application, httpx.ASGITransport(app=create_app(application, settings))


@pytest.fixture
async def client(
    api: tuple[TaskApplicationService, httpx.ASGITransport],
) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=api[1], base_url="http://test") as http:
        http.headers["x-api-key"] = "test-control-key"
        yield http


async def create_task(client: httpx.AsyncClient, key: str = "submission-key") -> dict[str, object]:
    response = await client.post(
        "/v1/tasks",
        headers={"Idempotency-Key": key},
        json={"repository": "owner/repository", "instruction": "Inspect the repository"},
    )
    assert response.status_code == 202
    return response.json()


async def test_task_routes_and_idempotency(client: httpx.AsyncClient) -> None:
    created = await create_task(client)
    duplicate = await create_task(client)
    assert duplicate["duplicate"] is True
    task_id = cast(dict[str, object], created["task"])["id"]
    assert (await client.get(f"/v1/tasks/{task_id}")).status_code == 200
    assert (await client.get("/v1/tasks?offset=0&limit=10")).json()["total"] == 1
    assert (await client.get(f"/v1/tasks/{task_id}/evidence")).status_code == 200
    assert (await client.get(f"/v1/tasks/{task_id}/reviews")).status_code == 200
    assert (
        await client.post(f"/v1/tasks/{task_id}/approvals", json={"reason": "reviewed"})
    ).status_code == 409
    assert (
        await client.post(f"/v1/tasks/{task_id}/rejections", json={"reason": "rejected"})
    ).status_code == 409
    cancelled = await client.post(
        f"/v1/tasks/{task_id}/cancel", json={"reason": "operator requested"}
    )
    assert cancelled.json()["status"] == "cancelled"
    assert (await client.post(f"/v1/tasks/{task_id}/retry")).status_code == 200


async def test_validation_resources_providers_models_and_health(client: httpx.AsyncClient) -> None:
    validation = await client.post(
        "/v1/tasks/validate",
        json={"repository": "owner/repository", "instruction": "Validate this task"},
    )
    assert validation.json()["valid"] is True
    await create_task(client, "repository-list-key")
    assert (await client.get("/v1/repositories")).status_code == 200
    assert (await client.get("/v1/repositories/owner/repository")).status_code == 200
    assert len((await client.get("/v1/providers")).json()) == 3
    assert len((await client.get("/v1/models")).json()) == 3
    assert (await client.get("/health/live")).json()["status"] == "live"
    assert (await client.get("/health/ready")).json()["status"] == "ready"
    assert (await client.get("/metrics")).status_code == 200


async def test_authentication_validation_pagination_and_error_contract(
    api: tuple[TaskApplicationService, httpx.ASGITransport],
) -> None:
    async with httpx.AsyncClient(transport=api[1], base_url="http://test") as anonymous:
        denied = await anonymous.get("/v1/tasks")
        assert denied.status_code == 401
        assert denied.json()["error"]["code"] == "authentication_failed"
    async with httpx.AsyncClient(transport=api[1], base_url="http://test") as http:
        http.headers["x-api-key"] = "test-control-key"
        missing = await http.post(
            "/v1/tasks",
            json={"repository": "owner/repository", "instruction": "Valid task"},
        )
        assert missing.status_code == 422
        assert missing.json()["error"]["code"] == "validation_error"
        invalid_page = await http.get("/v1/tasks?offset=-1")
        assert invalid_page.status_code == 422
        not_found = await http.get("/v1/tasks/00000000-0000-0000-0000-000000000000")
        assert not_found.status_code == 404
        assert "request_id" in not_found.json()["error"]


async def test_openapi_contains_every_control_route(client: httpx.AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).json()
    required = {
        "/v1/tasks",
        "/v1/tasks/validate",
        "/v1/tasks/{task_id}",
        "/v1/tasks/{task_id}/cancel",
        "/v1/tasks/{task_id}/retry",
        "/v1/tasks/{task_id}/evidence",
        "/v1/tasks/{task_id}/reviews",
        "/v1/tasks/{task_id}/approvals",
        "/v1/tasks/{task_id}/rejections",
        "/v1/repositories",
        "/v1/repositories/{repository_id}",
        "/v1/providers",
        "/v1/models",
        "/v1/webhooks/github",
        "/health/live",
        "/health/ready",
        "/metrics",
    }
    assert required <= set(schema["paths"])


async def test_body_limit_rate_limit_and_webhook_signature(
    api: tuple[TaskApplicationService, httpx.ASGITransport],
) -> None:
    limited_settings = Settings(
        control_plane_api_key=SecretStr("test-control-key"),
        github_webhook_secret=SecretStr("webhook-secret"),
        api_body_limit_bytes=64,
        api_rate_limit_requests=1,
    )
    transport = httpx.ASGITransport(app=create_app(api[0], limited_settings))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        http.headers["x-api-key"] = "test-control-key"
        oversized = await http.post(
            "/v1/tasks/validate",
            content=b"x" * 65,
            headers={"content-type": "application/json"},
        )
        assert oversized.status_code == 413
    rate_transport = httpx.ASGITransport(
        app=create_app(
            api[0],
            limited_settings.model_copy(update={"api_body_limit_bytes": 1024}),
        )
    )
    async with httpx.AsyncClient(transport=rate_transport, base_url="http://test") as http:
        http.headers["x-api-key"] = "test-control-key"
        assert (await http.get("/v1/tasks")).status_code == 200
        assert (await http.get("/v1/tasks")).status_code == 429
    webhook_transport = httpx.ASGITransport(app=create_app(api[0], limited_settings))
    body = b'{"action":"opened"}'
    signature = "sha256=" + hmac.new(b"webhook-secret", body, hashlib.sha256).hexdigest()
    async with httpx.AsyncClient(transport=webhook_transport, base_url="http://test") as http:
        accepted = await http.post(
            "/v1/webhooks/github",
            content=body,
            headers={"X-Hub-Signature-256": signature},
        )
        assert accepted.status_code == 202
    denied_transport = httpx.ASGITransport(app=create_app(api[0], limited_settings))
    async with httpx.AsyncClient(transport=denied_transport, base_url="http://test") as http:
        denied = await http.post(
            "/v1/webhooks/github",
            content=body,
            headers={"X-Hub-Signature-256": "sha256=bad"},
        )
        assert denied.status_code == 401
