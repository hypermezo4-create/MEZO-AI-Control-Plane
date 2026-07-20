import asyncio
import time
from typing import Any

import httpx

from mezo_control_plane.core.domain import ModelRequest, ModelResponse
from mezo_control_plane.providers.base import (
    ProviderError,
    ProviderFailureType,
    ProviderHealth,
)
from mezo_control_plane.providers.resilience import CircuitBreaker


def classify_status(response: httpx.Response) -> ProviderError:
    retry_after = response.headers.get("retry-after")
    retry_seconds = float(retry_after) if retry_after and retry_after.isdigit() else None
    if response.status_code == 401:
        return ProviderError(
            ProviderFailureType.AUTHENTICATION, "Provider authentication failed", retryable=False
        )
    if response.status_code == 403:
        return ProviderError(
            ProviderFailureType.PERMISSION, "Provider permission denied", retryable=False
        )
    if response.status_code == 429:
        failure_type = (
            ProviderFailureType.QUOTA
            if "quota" in response.text.lower()
            else ProviderFailureType.RATE_LIMIT
        )
        return ProviderError(
            failure_type,
            "Provider capacity limit exceeded",
            retryable=True,
            retry_after_seconds=retry_seconds,
        )
    if response.status_code >= 500:
        return ProviderError(
            ProviderFailureType.SERVER, "Provider service unavailable", retryable=True
        )
    return ProviderError(ProviderFailureType.SERVER, "Provider request rejected", retryable=False)


class GeminiProvider:
    def __init__(
        self,
        name: str,
        api_key: str,
        project_id: str,
        models: frozenset[str],
        *,
        concurrency: int = 2,
        timeout_seconds: float = 120,
        retry_budget: int = 2,
        client: httpx.AsyncClient | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        self.name = name
        self.models = models
        self._api_key = api_key
        self._project_id = project_id
        self._timeout = timeout_seconds
        self._retries = retry_budget
        self._client = client or httpx.AsyncClient(
            base_url="https://generativelanguage.googleapis.com/v1beta"
        )
        self._semaphore = asyncio.Semaphore(concurrency)
        self._circuit = circuit_breaker or CircuitBreaker()
        self._active = 0
        self._requests = 0
        self._failures = 0
        self._latency_total = 0.0
        self._input_tokens = 0
        self._output_tokens = 0

    async def generate(
        self,
        request: ModelRequest,
        model: str,
        *,
        deadline_seconds: float | None = None,
        cancellation: asyncio.Event | None = None,
    ) -> ModelResponse:
        if not self._api_key:
            raise ProviderError(
                ProviderFailureType.AUTHENTICATION, "Gemini key is not configured", retryable=False
            )
        if model not in self.models:
            raise ProviderError(
                ProviderFailureType.UNKNOWN_MODEL, "Gemini model is not pinned", retryable=False
            )
        if not self._circuit.allow():
            raise ProviderError(
                ProviderFailureType.SERVER, "Gemini circuit is open", retryable=True
            )
        timeout = min(deadline_seconds or self._timeout, self._timeout)
        last_error: ProviderError | None = None
        async with self._semaphore:
            self._active += 1
            try:
                for attempt in range(self._retries + 1):
                    if cancellation and cancellation.is_set():
                        raise ProviderError(
                            ProviderFailureType.CANCELLATION, "Request cancelled", retryable=False
                        )
                    try:
                        async with asyncio.timeout(timeout):
                            return await self._request(request, model)
                    except TimeoutError:
                        last_error = ProviderError(
                            ProviderFailureType.TIMEOUT, "Gemini request timed out", retryable=True
                        )
                    except httpx.RequestError as error:
                        last_error = ProviderError(
                            ProviderFailureType.CONNECTION,
                            "Gemini connection failed",
                            retryable=True,
                        )
                        last_error.__cause__ = error
                    except ProviderError as error:
                        last_error = error
                    self._failures += 1
                    assert last_error is not None
                    if not last_error.retryable or attempt >= self._retries:
                        self._circuit.failure()
                        raise last_error
                    await asyncio.sleep(last_error.retry_after_seconds or 0)
            finally:
                self._active -= 1
        raise last_error or ProviderError(
            ProviderFailureType.SERVER, "Gemini failed", retryable=True
        )

    async def _request(self, request: ModelRequest, model: str) -> ModelResponse:
        started = time.monotonic()
        contents = [
            {"role": message.role, "parts": [{"text": message.content}]}
            for message in request.messages
        ]
        payload: dict[str, object] = {
            "contents": contents,
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_output_tokens,
            },
        }
        if request.system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": request.system_instruction}]}
        response = await self._client.post(
            f"/models/{model}:generateContent",
            headers={"x-goog-api-key": self._api_key, "x-goog-user-project": self._project_id},
            json=payload,
        )
        if response.status_code >= 400:
            raise classify_status(response)
        try:
            body: dict[str, Any] = response.json()
            candidate = body["candidates"][0]
            if candidate.get("finishReason") in {"SAFETY", "PROHIBITED_CONTENT"}:
                raise ProviderError(
                    ProviderFailureType.CONTENT_POLICY,
                    "Gemini content policy rejected the request",
                    retryable=False,
                )
            text = "".join(part["text"] for part in candidate["content"]["parts"] if "text" in part)
            if not text:
                raise KeyError("empty text")
            usage = body.get("usageMetadata", {})
            input_tokens = int(usage.get("promptTokenCount", 0))
            output_tokens = int(usage.get("candidatesTokenCount", 0))
        except ProviderError:
            raise
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise ProviderError(
                ProviderFailureType.MALFORMED_OUTPUT,
                "Gemini returned malformed output",
                retryable=False,
            ) from error
        self._requests += 1
        self._input_tokens += input_tokens
        self._output_tokens += output_tokens
        self._latency_total += time.monotonic() - started
        self._circuit.success()
        return ModelResponse(
            provider=self.name,
            model=model,
            text=text,
            request_id=response.headers.get("x-request-id"),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    async def healthy(self) -> bool:
        return bool(self._api_key and self._project_id and self._circuit.allow())

    def health(self) -> ProviderHealth:
        latency = self._latency_total / self._requests if self._requests else None
        return ProviderHealth(
            self.name,
            bool(self._api_key and self._project_id and self._circuit.allow()),
            self._circuit.state.value,
            self._active,
            self._failures,
            latency,
        )

    async def close(self) -> None:
        await self._client.aclose()
