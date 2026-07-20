from __future__ import annotations

import httpx

from mezo_control_plane.core.domain import ModelRequest, ModelResponse
from mezo_control_plane.core.errors import ProviderUnavailable


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, timeout_seconds: float = 120) -> None:
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            base_url="https://generativelanguage.googleapis.com/v1beta",
            timeout=timeout_seconds,
        )

    async def generate(self, request: ModelRequest, model: str) -> ModelResponse:
        if not self._api_key:
            raise ProviderUnavailable("Gemini API key is not configured")
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
            headers={"x-goog-api-key": self._api_key},
            json=payload,
        )
        if response.status_code >= 400:
            raise ProviderUnavailable(
                f"Gemini request failed with status {response.status_code}: {response.text[:300]}"
            )
        body = response.json()
        try:
            text = "".join(
                part.get("text", "")
                for part in body["candidates"][0]["content"]["parts"]
                if isinstance(part, dict)
            )
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderUnavailable("Gemini returned an unexpected response shape") from exc
        return ModelResponse(
            provider=self.name,
            model=model,
            text=text,
            request_id=response.headers.get("x-request-id"),
        )

    async def healthy(self) -> bool:
        return bool(self._api_key)

    async def close(self) -> None:
        await self._client.aclose()
