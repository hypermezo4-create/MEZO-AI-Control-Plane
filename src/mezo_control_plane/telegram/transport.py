import asyncio
from typing import Protocol

import httpx


class TelegramTransportError(Exception):
    pass


class TelegramFloodWait(TelegramTransportError):
    def __init__(self, retry_after_seconds: float) -> None:
        super().__init__("Telegram requested flood-control backoff")
        self.retry_after_seconds = retry_after_seconds


class TelegramTransport(Protocol):
    async def send_message(self, chat_id: int, text: str, parse_mode: str) -> None: ...
    async def answer_callback(self, callback_id: str, text: str) -> None: ...
    async def healthy(self) -> bool: ...
    async def close(self) -> None: ...


class HttpTelegramTransport:
    def __init__(self, token: str, timeout_seconds: float = 15) -> None:
        self._configured = bool(token)
        self._client = httpx.AsyncClient(
            base_url=f"https://api.telegram.org/bot{token}", timeout=timeout_seconds
        )

    async def send_message(self, chat_id: int, text: str, parse_mode: str = "HTML") -> None:
        await self._post(
            "/sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        )

    async def answer_callback(self, callback_id: str, text: str) -> None:
        await self._post("/answerCallbackQuery", {"callback_query_id": callback_id, "text": text})

    async def _post(self, path: str, payload: dict[str, object]) -> None:
        if not self._configured:
            raise TelegramTransportError("Telegram transport is not configured")
        try:
            response = await self._client.post(path, json=payload)
        except httpx.HTTPError as error:
            raise TelegramTransportError("Telegram transport request failed") from error
        if response.status_code == 429:
            retry_after = float(response.json().get("parameters", {}).get("retry_after", 1))
            raise TelegramFloodWait(retry_after)
        if response.status_code >= 400:
            raise TelegramTransportError(
                f"Telegram transport returned status {response.status_code}"
            )

    async def healthy(self) -> bool:
        if not self._configured:
            return False
        try:
            return (await self._client.get("/getMe")).status_code == 200
        except httpx.HTTPError:
            return False

    async def close(self) -> None:
        await self._client.aclose()


async def send_with_flood_wait(
    transport: TelegramTransport,
    chat_id: int,
    text: str,
    parse_mode: str = "HTML",
    maximum_retries: int = 2,
) -> None:
    for attempt in range(maximum_retries + 1):
        try:
            await transport.send_message(chat_id, text, parse_mode)
            return
        except TelegramFloodWait as error:
            if attempt == maximum_retries:
                raise
            await asyncio.sleep(error.retry_after_seconds)
