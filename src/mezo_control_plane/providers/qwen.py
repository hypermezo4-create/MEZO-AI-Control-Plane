from __future__ import annotations

import httpx

from mezo_control_plane.core.domain import ModelRequest, ModelResponse
from mezo_control_plane.core.errors import ProviderUnavailable


class QwenProvider:
    name = "qwen"

    def __init__(self, base_url: str, api_key: str, timeout_seconds: float = 120) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = httpx.AsyncClient(timeout=timeout_seconds)

    async def generate(self, request: ModelRequest, model: str) -> ModelResponse:
        if not self._base_url:
            raise ProviderUnavailable("Qwen endpoint is not configured")
        messages: list[dict[str, str]] = []
        if request.system_instruction:
            messages.append({"role": "system", "content": request.system_instruction})
        messages.extend(message.model_dump() for message in request.messages)
        response = await self._client.post(
            f"{self._base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": model,
                "messages": messages,
                "temperature": request.temperature,
                "max_tokens": request.max_output_tokens,
            },
        )
        if response.status_code >= 400:
            raise ProviderUnavailable(
                f"Qwen request failed with status {response.status_code}: {response.text[:300]}"
            )
        body = response.json()
        try:
            text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderUnavailable("Qwen returned an unexpected response shape") from exc
        return ModelResponse(
            provider=self.name,
            model=model,
            text=text,
            request_id=response.headers.get("x-request-id"),
        )

    async def healthy(self) -> bool:
        if not self._base_url:
            return False
        try:
            response = await self._client.get(
                f"{self._base_url}/models",
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
            return response.status_code < 500
        except httpx.HTTPError:
            return False

    async def close(self) -> None:
        await self._client.aclose()
