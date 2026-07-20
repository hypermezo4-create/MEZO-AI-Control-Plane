import time
from collections import defaultdict, deque
from uuid import UUID

from mezo_control_plane.application.errors import ApplicationError
from mezo_control_plane.application.tasks import TaskApplicationService
from mezo_control_plane.core.domain import TaskRequest
from mezo_control_plane.telegram.formatting import chunks, escape, evidence_summary, task_status
from mezo_control_plane.telegram.models import CommandRequest, TelegramRole, TelegramUpdate
from mezo_control_plane.telegram.security import (
    CallbackSigner,
    CallbackValidationError,
    TelegramAccessPolicy,
)
from mezo_control_plane.telegram.transport import (
    TelegramTransport,
    send_with_flood_wait,
)

_COMMAND_ROLES: dict[str, frozenset[TelegramRole]] = {
    "start": frozenset(TelegramRole),
    "help": frozenset(TelegramRole),
    "status": frozenset(TelegramRole),
    "analyze": frozenset({TelegramRole.OWNER, TelegramRole.OPERATOR}),
    "fix": frozenset({TelegramRole.OWNER, TelegramRole.OPERATOR}),
    "review": frozenset({TelegramRole.OWNER, TelegramRole.OPERATOR, TelegramRole.REVIEWER}),
    "cancel": frozenset({TelegramRole.OWNER, TelegramRole.OPERATOR}),
    "approve": frozenset({TelegramRole.OWNER, TelegramRole.REVIEWER}),
    "reject": frozenset({TelegramRole.OWNER, TelegramRole.REVIEWER}),
    "deploy": frozenset({TelegramRole.OWNER}),
}


class TelegramControlSurface:
    def __init__(
        self,
        service: TaskApplicationService,
        transport: TelegramTransport,
        access: TelegramAccessPolicy,
        callbacks: CallbackSigner,
        rate_limit: int = 20,
        rate_window_seconds: int = 60,
    ) -> None:
        self._service = service
        self._transport = transport
        self._access = access
        self._callbacks = callbacks
        self._rate_limit = rate_limit
        self._rate_window = rate_window_seconds
        self._updates: set[int] = set()
        self._update_order: deque[int] = deque(maxlen=10_000)
        self._rates: dict[str, deque[float]] = defaultdict(deque)
        self._closing = False

    async def handle(self, update: TelegramUpdate) -> None:
        if self._closing or update.update_id in self._updates:
            return
        self._remember(update.update_id)
        target = update.message or update.callback
        if target is None:
            return
        role = self._access.role_for(target.user_id)
        if role is None or target.chat_id not in self._access.allowed_chats:
            return
        if not self._allow(target.user_id, target.chat_id):
            await self._send(target.chat_id, "Rate limit exceeded. Try again later.")
            return
        if update.callback is not None:
            await self._handle_callback(update, role)
            return
        assert update.message is not None
        command = self._parse(update, role)
        if command is None:
            await self._send(target.chat_id, "Use /help to list supported commands.")
            return
        if role not in _COMMAND_ROLES.get(command.name, frozenset()):
            await self._send(target.chat_id, "You are not permitted to use this command.")
            return
        try:
            response = await self._execute(command)
        except (ApplicationError, ValueError) as error:
            response = f"Request failed: {type(error).__name__}"
        await self._send(target.chat_id, response)

    async def _execute(self, command: CommandRequest) -> str:
        if command.name in {"start", "help"}:
            return (
                "MEZO control commands: /analyze /fix /review /status /cancel "
                "/approve /reject /deploy"
            )
        if command.name in {"analyze", "fix", "review"}:
            repository, instruction = self._repository_instruction(command.arguments)
            task, enqueue_result = await self._service.create_task(
                TaskRequest(
                    repository=repository,
                    instruction=f"{command.name}: {instruction}",
                ),
                f"telegram:{command.update_id}",
            )
            return task_status(task) + (
                "\nQueued." if enqueue_result.accepted else "\nAlready submitted."
            )
        task_id = UUID(command.arguments.strip())
        if command.name == "status":
            task = await self._service.get_task(task_id)
            evidence = await self._service.evidence(task_id)
            return f"{task_status(task)}\n{evidence_summary(evidence)}"
        if command.name == "cancel":
            cancellation_result = await self._service.cancel_task(
                task_id, f"telegram:{command.user_id}", "Telegram cancellation"
            )
            return f"Cancellation: {cancellation_result.value}"
        if command.name in {"approve", "reject"}:
            task = await self._service.decide(task_id, command.name == "approve")
            return task_status(task)
        if command.name == "deploy":
            task = await self._service.get_task(task_id)
            return f"Deployment requires the later deployment policy phase.\n{task_status(task)}"
        raise ValueError("Unknown Telegram command")

    async def _handle_callback(self, update: TelegramUpdate, role: TelegramRole) -> None:
        assert update.callback is not None
        try:
            payload = self._callbacks.verify(update.callback.data)
            action = payload["action"]
            if action not in {"approve", "reject"} or role not in _COMMAND_ROLES[action]:
                raise CallbackValidationError("Callback action is not permitted")
            await self._service.decide(UUID(payload["task_id"]), action == "approve")
            await self._transport.answer_callback(update.callback.callback_id, f"Task {action}d")
        except (CallbackValidationError, ApplicationError, ValueError):
            await self._transport.answer_callback(
                update.callback.callback_id, "Callback is invalid"
            )

    async def _send(self, chat_id: int, text: str) -> None:
        safe = escape(text) if "<b>" not in text and "<code>" not in text else text
        for part in chunks(safe):
            await send_with_flood_wait(self._transport, chat_id, part)

    def _parse(self, update: TelegramUpdate, role: TelegramRole) -> CommandRequest | None:
        assert update.message is not None
        text = update.message.text.strip()
        if not text.startswith("/"):
            return None
        name, _, arguments = text.partition(" ")
        name = name[1:].split("@", 1)[0].lower()
        return CommandRequest(
            name=name,
            arguments=arguments,
            update_id=update.update_id,
            chat_id=update.message.chat_id,
            user_id=update.message.user_id,
            role=role,
        )

    def _allow(self, user_id: int, chat_id: int) -> bool:
        now = time.monotonic()
        for identity in (f"user:{user_id}", f"chat:{chat_id}"):
            bucket = self._rates[identity]
            while bucket and bucket[0] <= now - self._rate_window:
                bucket.popleft()
            if len(bucket) >= self._rate_limit:
                return False
            bucket.append(now)
        return True

    def _remember(self, update_id: int) -> None:
        if len(self._update_order) == self._update_order.maxlen:
            self._updates.discard(self._update_order[0])
        self._update_order.append(update_id)
        self._updates.add(update_id)

    @staticmethod
    def _repository_instruction(arguments: str) -> tuple[str, str]:
        repository, separator, instruction = arguments.strip().partition(" ")
        if not separator or not instruction:
            raise ValueError("Command requires repository and instruction")
        return repository, instruction

    async def healthy(self) -> bool:
        return not self._closing and await self._transport.healthy()

    async def shutdown(self) -> None:
        self._closing = True
        await self._transport.close()
