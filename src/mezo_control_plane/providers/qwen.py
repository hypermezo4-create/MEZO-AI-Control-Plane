import asyncio
from typing import Any

import httpx

from mezo_control_plane.core.domain import ModelRequest, ModelResponse
from mezo_control_plane.providers.base import ProviderError, ProviderFailureType
from mezo_control_plane.providers.gemini import classify_status
from mezo_control_plane.providers.resilience import CircuitBreaker


class QwenProvider:
    name = "qwen"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        models: frozenset[str],
        *,
        concurrency: int = 4,
        timeout_seconds: float = 120,
        client: httpx.AsyncClient | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        self.models = models
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._client = client or httpx.AsyncClient()
        self._semaphore = asyncio.Semaphore(concurrency)
        self._circuit = circuit_breaker or CircuitBreaker()

    async def generate(
        self,
        request: ModelRequest,
        model: str,
        *,
        deadline_seconds: float | None = None,
        cancellation: asyncio.Event | None = None,
    ) -> ModelResponse:
        if not self._base_url or not self._api_key:
            raise ProviderError(
                ProviderFailureType.AUTHENTICATION, "Qwen is not configured", retryable=False
            )
        if model not in self.models:
            raise ProviderError(
                ProviderFailureType.UNKNOWN_MODEL, "Qwen model is not pinned", retryable=False
            )
        if cancellation and cancellation.is_set():
            raise ProviderError(
                ProviderFailureType.CANCELLATION, "Request cancelled", retryable=False
            )
        if not self._circuit.allow():
            raise ProviderError(ProviderFailureType.SERVER, "Qwen circuit is open", retryable=True)
        messages: list[dict[str, str]] = []
        if request.system_instruction:
            messages.append({"role": "system", "content": request.system_instruction})
        messages.extend(message.model_dump() for message in request.messages)
        try:
            async with (
                self._semaphore,
                asyncio.timeout(min(deadline_seconds or self._timeout, self._timeout)),
            ):
                response = await self._client.post(
                    f"{self._base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={
                        "model": model,
                        "messages": messages,
                        "temperature": request.temperature,
                        "max_tokens": request.max_output_tokens,
                        "stream": False,
                    },
                )
        except TimeoutError as error:
            self._circuit.failure()
            raise ProviderError(
                ProviderFailureType.TIMEOUT, "Qwen request timed out", retryable=True
            ) from error
        except httpx.RequestError as error:
            self._circuit.failure()
            raise ProviderError(
                ProviderFailureType.CONNECTION, "Qwen connection failed", retryable=True
            ) from error
        if response.status_code >= 400:
            provider_error = classify_status(response)
            if provider_error.retryable:
                self._circuit.failure()
            raise provider_error
        try:
            body: dict[str, Any] = response.json()
            message = body["choices"][0]["message"]
            text = message.get("content") or ""
            tool_calls = message.get("tool_calls") or []
            if not text and not tool_calls:
                raise KeyError("empty response")
            usage = body.get("usage", {})
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise ProviderError(
                ProviderFailureType.MALFORMED_OUTPUT,
                "Qwen returned invalid model output",
                retryable=False,
            ) from error
        self._circuit.success()
        return ModelResponse(
            provider=self.name,
            model=model,
            text=text,
            request_id=response.headers.get("x-request-id"),
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
            tool_calls=tool_calls,
        )

    async def models_available(self) -> frozenset[str]:
        try:
            response = await self._client.get(
                f"{self._base_url}/models",
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
            response.raise_for_status()
            return frozenset(item["id"] for item in response.json()["data"])
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            raise ProviderError(
                ProviderFailureType.CONNECTION, "Qwen model probe failed", retryable=True
            ) from error

    async def healthy(self) -> bool:
        if not self._base_url or not self._api_key or not self._circuit.allow():
            return False
        try:
            available = await self.models_available()
            return bool(self.models <= available)
        except ProviderError:
            return False

    async def close(self) -> None:
        await self._client.aclose()
