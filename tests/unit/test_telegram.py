from typing import cast
from uuid import UUID

import pytest

from mezo_control_plane.application.tasks import TaskApplicationService
from mezo_control_plane.core.domain import EvidenceItem, TaskRecord, TaskRequest, TaskState
from mezo_control_plane.queue.cancellation import CancellationResult
from mezo_control_plane.queue.producer import EnqueueResult
from mezo_control_plane.telegram.bot import TelegramControlSurface
from mezo_control_plane.telegram.formatting import chunks, escape
from mezo_control_plane.telegram.models import (
    TelegramCallback,
    TelegramMessage,
    TelegramUpdate,
)
from mezo_control_plane.telegram.security import (
    CallbackSigner,
    CallbackValidationError,
    TelegramAccessPolicy,
)
from mezo_control_plane.telegram.transport import (
    TelegramFloodWait,
    TelegramTransport,
    TelegramTransportError,
)


class FakeService:
    def __init__(self) -> None:
        self.task = TaskRecord(
            request=TaskRequest(repository="owner/repository", instruction="Inspect this")
        )
        self.calls: list[str] = []

    async def create_task(self, request: TaskRequest, key: str) -> tuple[TaskRecord, EnqueueResult]:
        self.calls.append("create")
        return self.task, EnqueueResult(message_id="message", accepted=True)

    async def get_task(self, task_id: UUID) -> TaskRecord:
        self.calls.append("get")
        return self.task

    async def evidence(self, task_id: UUID) -> list[EvidenceItem]:
        self.calls.append("evidence")
        return [EvidenceItem(kind="test", summary="API_KEY=do-not-leak")]

    async def cancel_task(self, task_id: UUID, actor: str, reason: str) -> CancellationResult:
        self.calls.append("cancel")
        return CancellationResult.CANCELLED

    async def decide(self, task_id: UUID, approved: bool) -> TaskRecord:
        self.calls.append("approve" if approved else "reject")
        return self.task.model_copy(
            update={"state": TaskState.QUEUED if approved else TaskState.CANCELLED}
        )


class FakeTransport:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []
        self.callbacks: list[str] = []
        self.closed = False
        self.flood_once = False

    async def send_message(self, chat_id: int, text: str, parse_mode: str) -> None:
        if self.flood_once:
            self.flood_once = False
            raise TelegramFloodWait(0)
        self.messages.append((chat_id, text))

    async def answer_callback(self, callback_id: str, text: str) -> None:
        self.callbacks.append(text)

    async def healthy(self) -> bool:
        return True

    async def close(self) -> None:
        self.closed = True


def surface(
    role: str = "owner", rate_limit: int = 100
) -> tuple[TelegramControlSurface, FakeService, FakeTransport, CallbackSigner]:
    service = FakeService()
    transport = FakeTransport()
    owners = frozenset({1}) if role == "owner" else frozenset()
    operators = frozenset({1}) if role == "operator" else frozenset()
    reviewers = frozenset({1}) if role == "reviewer" else frozenset()
    access = TelegramAccessPolicy(frozenset({1}), frozenset({10}), owners, operators, reviewers)
    signer = CallbackSigner("telegram-callback-secret")
    bot = TelegramControlSurface(
        cast(TaskApplicationService, service),
        cast(TelegramTransport, transport),
        access,
        signer,
        rate_limit=rate_limit,
    )
    return bot, service, transport, signer


def message(update_id: int, text: str, user_id: int = 1, chat_id: int = 10) -> TelegramUpdate:
    return TelegramUpdate(
        update_id=update_id,
        message=TelegramMessage(message_id=update_id, chat_id=chat_id, user_id=user_id, text=text),
    )


@pytest.mark.parametrize("command", ["start", "help"])
async def test_help_commands(command: str) -> None:
    bot, _, transport, _ = surface()
    await bot.handle(message(1, f"/{command}"))
    assert command == "start" or "control commands" in transport.messages[0][1]


@pytest.mark.parametrize("command", ["analyze", "fix", "review"])
async def test_creation_commands_use_shared_application_service(command: str) -> None:
    bot, service, transport, _ = surface()
    await bot.handle(message(1, f"/{command} owner/repository inspect this"))
    assert service.calls == ["create"]
    assert transport.messages


async def test_status_cancel_approve_reject_and_deploy_commands() -> None:
    bot, service, transport, _ = surface()
    task_id = service.task.id
    for index, command in enumerate(
        ["status", "cancel", "approve", "reject", "deploy"], start=1
    ):
        await bot.handle(message(index, f"/{command} {task_id}"))
    assert {"get", "evidence", "cancel", "approve", "reject"} <= set(service.calls)
    assert len(transport.messages) == 5
    assert "do-not-leak" not in "".join(item[1] for item in transport.messages)


async def test_allowlists_roles_deduplication_and_rate_limit() -> None:
    bot, service, transport, _ = surface(role="reviewer", rate_limit=1)
    await bot.handle(message(1, "/cancel 00000000-0000-0000-0000-000000000000"))
    assert "not permitted" in transport.messages[-1][1]
    await bot.handle(message(1, "/help"))
    assert len(transport.messages) == 1
    await bot.handle(message(2, "/help", user_id=9))
    await bot.handle(message(3, "/help", chat_id=99))
    assert len(transport.messages) == 1
    await bot.handle(message(4, "/help"))
    assert "Rate limit" in transport.messages[-1][1]
    assert not service.calls


async def test_signed_callback_tamper_expiry_and_replay() -> None:
    bot, service, transport, signer = surface(role="reviewer")
    token = signer.sign("approve", str(service.task.id), now=100)
    valid = TelegramUpdate(
        update_id=1,
        callback=TelegramCallback(callback_id="one", chat_id=10, user_id=1, data=token),
    )
    # The signer uses wall time in bot handling, so a deterministic non-expired token is used here.
    live = signer.sign("approve", str(service.task.id))
    valid.callback = valid.callback.model_copy(update={"data": live})
    await bot.handle(valid)
    assert transport.callbacks[-1] == "Task approved"
    await bot.handle(valid.model_copy(update={"update_id": 2}))
    assert transport.callbacks[-1] == "Callback is invalid"
    tampered = live[:-1] + ("0" if live[-1] != "0" else "1")
    with pytest.raises(CallbackValidationError):
        CallbackSigner("telegram-callback-secret").verify(tampered)
    with pytest.raises(CallbackValidationError):
        CallbackSigner("telegram-callback-secret").verify(token, now=1_000)


async def test_flood_wait_retry_chunking_escaping_shutdown_and_health() -> None:
    bot, _, transport, _ = surface()
    transport.flood_once = True
    await bot.handle(message(1, "/help"))
    assert transport.messages
    assert all(len(part) <= 64 for part in chunks("x" * 200, 64))
    assert escape("<tag> API_KEY=secret") == "&lt;tag&gt; API_KEY=[REDACTED]"
    assert await bot.healthy()
    await bot.shutdown()
    assert transport.closed


async def test_transport_failure_is_not_hidden() -> None:
    class BrokenTransport(FakeTransport):
        async def send_message(self, chat_id: int, text: str, parse_mode: str) -> None:
            raise TelegramTransportError("transport failed")

    bot, service, _, signer = surface()
    bot = TelegramControlSurface(
        cast(TaskApplicationService, service),
        cast(TelegramTransport, BrokenTransport()),
        TelegramAccessPolicy(
            frozenset({1}),
            frozenset({10}),
            frozenset({1}),
            frozenset(),
            frozenset(),
        ),
        signer,
    )
    with pytest.raises(TelegramTransportError):
        await bot.handle(message(1, "/help"))
