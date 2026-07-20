import asyncio
import os
from collections.abc import AsyncIterator
from typing import cast
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from redis.asyncio import Redis

from mezo_control_plane.api.main import create_app
from mezo_control_plane.application.tasks import TaskApplicationService
from mezo_control_plane.core.domain import ModelRequest, ModelResponse
from mezo_control_plane.core.settings import Settings
from mezo_control_plane.database.base import Base
from mezo_control_plane.database.evidence_ledger import EvidenceLedgerRepository
from mezo_control_plane.database.repositories import TaskRepository
from mezo_control_plane.database.session import create_engine, create_session_factory
from mezo_control_plane.model_router.router import ModelRole, ModelRouter, Route
from mezo_control_plane.providers.base import ModelProvider
from mezo_control_plane.queue.cancellation import CancellationService
from mezo_control_plane.queue.consumer import ClaimedTask, TaskConsumer
from mezo_control_plane.queue.dead_letter_queue import DeadLetterQueue
from mezo_control_plane.queue.producer import TaskProducer
from mezo_control_plane.queue.retry_scheduler import RetryScheduler
from mezo_control_plane.telegram.bot import TelegramControlSurface
from mezo_control_plane.telegram.models import TelegramMessage, TelegramUpdate
from mezo_control_plane.telegram.security import CallbackSigner, TelegramAccessPolicy
from mezo_control_plane.telegram.transport import TelegramTransport
from mezo_control_plane.worker.durable_execution import SqlAlchemyExecutionGateway
from mezo_control_plane.worker.failure_delivery import QueueFailureDispatcher
from mezo_control_plane.worker.registration import WorkerRegistry
from mezo_control_plane.worker.runtime import WorkerRuntime


class StaticProvider:
    name = "execution-provider"
    models = frozenset({"pinned-model"})

    async def generate(
        self,
        request: ModelRequest,
        model: str,
        *,
        deadline_seconds: float | None = None,
        cancellation: asyncio.Event | None = None,
    ) -> ModelResponse:
        return ModelResponse(
            provider=self.name,
            model=model,
            text="execution evidence",
            input_tokens=4,
            output_tokens=2,
        )

    async def healthy(self) -> bool:
        return True


class ObservedConsumer:
    def __init__(self, consumer: TaskConsumer) -> None:
        self._consumer = consumer
        self.acknowledged = asyncio.Event()

    async def claim(self, visibility_seconds: int = 60) -> ClaimedTask | None:
        return await self._consumer.claim(visibility_seconds)

    async def renew_lease(self, claimed: ClaimedTask, visibility_seconds: int = 60) -> bool:
        return await self._consumer.renew_lease(claimed, visibility_seconds)

    async def acknowledge(self, claimed: ClaimedTask) -> bool:
        result = await self._consumer.acknowledge(claimed)
        if result:
            self.acknowledged.set()
        return result


class TelegramRecorder:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send_message(self, chat_id: int, text: str, parse_mode: str) -> None:
        self.messages.append(text)

    async def answer_callback(self, callback_id: str, text: str) -> None:
        pass

    async def healthy(self) -> bool:
        return True

    async def close(self) -> None:
        pass


@pytest.fixture
async def infrastructure() -> AsyncIterator[tuple[TaskRepository, Redis, str]]:
    database_url = os.getenv("DATABASE_TEST_URL")
    redis_url = os.getenv("REDIS_TEST_URL")
    if not database_url or not redis_url:
        pytest.skip("DATABASE_TEST_URL and REDIS_TEST_URL are required")
    engine = create_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    redis = Redis.from_url(redis_url, decode_responses=True)
    prefix = f"mezo:flow:{uuid4()}"
    yield TaskRepository(create_session_factory(engine)), redis, prefix
    keys = [key async for key in redis.scan_iter(match=f"{prefix}:*")]
    if keys:
        await redis.delete(*keys)
    await redis.aclose()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def healthy() -> bool:
    return True


async def test_authenticated_api_worker_provider_and_telegram_flow(
    infrastructure: tuple[TaskRepository, Redis, str],
) -> None:
    repository, redis, prefix = infrastructure
    producer = TaskProducer(redis, prefix)
    cancellation = CancellationService(redis, prefix)
    service = TaskApplicationService(repository, producer, cancellation, healthy, healthy, healthy)
    consumer = ObservedConsumer(TaskConsumer(redis, "worker-flow", prefix))
    persistence = SqlAlchemyExecutionGateway(repository.session_factory)
    router = ModelRouter(
        {ModelRole.EXECUTOR: [Route(cast(ModelProvider, StaticProvider()), "pinned-model")]}
    )

    async def handler(delivery: ClaimedTask, cancelled: asyncio.Event) -> str:
        response = await router.generate(
            ModelRole.EXECUTOR,
            ModelRequest(messages=[]),
            cancellation=cancelled,
        )
        return response.text

    runtime = WorkerRuntime(
        "worker-flow",
        cast(TaskConsumer, consumer),
        WorkerRegistry(redis, "worker-flow", 2, prefix),
        persistence,
        handler,
        QueueFailureDispatcher(
            cast(TaskConsumer, consumer),
            RetryScheduler(redis, prefix),
            DeadLetterQueue(redis, prefix),
            "worker-flow",
        ),
        concurrency=2,
        visibility_seconds=3,
        heartbeat_interval_seconds=0.05,
        cancellation_service=cancellation,
    )
    worker = asyncio.create_task(runtime.run())
    app = create_app(
        service,
        Settings(control_plane_api_key=SecretStr("integration-control-key")),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post(
            "/v1/tasks",
            headers={
                "x-api-key": "integration-control-key",
                "Idempotency-Key": "cross-phase-submission",
            },
            json={
                "repository": "owner/repository",
                "instruction": "Run the integrated execution flow",
            },
        )
        assert created.status_code == 202
        task_id = created.json()["task"]["id"]
        await asyncio.wait_for(consumer.acknowledged.wait(), timeout=5)
        status_response = await client.get(
            f"/v1/tasks/{task_id}", headers={"x-api-key": "integration-control-key"}
        )
        assert status_response.json()["state"] == "completed"
        evidence = await client.get(
            f"/v1/tasks/{task_id}/evidence",
            headers={"x-api-key": "integration-control-key"},
        )
        assert {item["kind"] for item in evidence.json()["items"]} == {
            "queue-claim",
            "execution-result",
        }
        report = await client.get(
            f"/v1/tasks/{task_id}/report",
            headers={"x-api-key": "integration-control-key"},
        )
        assert report.status_code == 200
        assert len(report.json()["evidence_digest"]) == 64
        ledger = EvidenceLedgerRepository(repository.session_factory)
        assert await ledger.verify(task_id)
        assert len(await ledger.entries(task_id)) == 2
    recorder = TelegramRecorder()
    bot = TelegramControlSurface(
        service,
        cast(TelegramTransport, recorder),
        TelegramAccessPolicy(
            frozenset({1}), frozenset({10}), frozenset({1}), frozenset(), frozenset()
        ),
        CallbackSigner("integration-callback-secret"),
    )
    await bot.handle(
        TelegramUpdate(
            update_id=1,
            message=TelegramMessage(
                message_id=1,
                chat_id=10,
                user_id=1,
                text=f"/status {task_id}",
            ),
        )
    )
    assert "completed" in recorder.messages[0]
    await runtime.shutdown(2)
    await worker
    assert await redis.hlen(f"{prefix}:inflight") == 0
