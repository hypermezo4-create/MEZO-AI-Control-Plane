import asyncio
from typing import Protocol

import httpx
from pydantic import BaseModel, Field

from mezo_control_plane.providers.base import ProviderError, ProviderFailureType


class EmbeddingVector(BaseModel):
    index: int = Field(ge=0)
    vector: list[float] = Field(min_length=1)


class EmbeddingBatch(BaseModel):
    provider: str
    model: str
    version: str
    dimensions: int = Field(gt=0)
    vectors: list[EmbeddingVector]


class EmbeddingsProvider(Protocol):
    async def embed(
        self,
        inputs: list[str],
        *,
        timeout_seconds: float | None = None,
        cancellation: asyncio.Event | None = None,
    ) -> EmbeddingBatch: ...


class OpenAICompatibleEmbeddings:
    def __init__(
        self,
        provider: str,
        base_url: str,
        api_key: str,
        model: str,
        version: str,
        *,
        maximum_batch: int = 64,
        maximum_input_characters: int = 32_000,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._provider = provider
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._version = version
        self._maximum_batch = maximum_batch
        self._maximum_input = maximum_input_characters
        self._client = client or httpx.AsyncClient()

    async def embed(
        self,
        inputs: list[str],
        *,
        timeout_seconds: float | None = None,
        cancellation: asyncio.Event | None = None,
    ) -> EmbeddingBatch:
        if not inputs or len(inputs) > self._maximum_batch:
            raise ValueError("Embedding batch size is outside configured limits")
        if any(not item or len(item) > self._maximum_input for item in inputs):
            raise ValueError("Embedding input is outside configured limits")
        if cancellation and cancellation.is_set():
            raise ProviderError(
                ProviderFailureType.CANCELLATION, "Embedding cancelled", retryable=False
            )
        if not self._base_url or not self._api_key:
            raise ProviderError(
                ProviderFailureType.AUTHENTICATION, "Embeddings are disabled", retryable=False
            )
        try:
            async with asyncio.timeout(timeout_seconds or 30):
                response = await self._client.post(
                    f"{self._base_url}/embeddings",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={"model": self._model, "input": inputs},
                )
            response.raise_for_status()
            data = sorted(response.json()["data"], key=lambda item: item["index"])
            vectors = [
                EmbeddingVector(index=item["index"], vector=item["embedding"]) for item in data
            ]
            dimensions = len(vectors[0].vector)
            if len(vectors) != len(inputs) or any(
                len(item.vector) != dimensions for item in vectors
            ):
                raise ValueError("Embedding response dimensions are inconsistent")
        except TimeoutError as error:
            raise ProviderError(
                ProviderFailureType.TIMEOUT, "Embedding request timed out", retryable=True
            ) from error
        except httpx.HTTPError as error:
            raise ProviderError(
                ProviderFailureType.CONNECTION, "Embedding request failed", retryable=True
            ) from error
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise ProviderError(
                ProviderFailureType.MALFORMED_OUTPUT,
                "Embedding provider returned invalid vectors",
                retryable=False,
            ) from error
        return EmbeddingBatch(
            provider=self._provider,
            model=self._model,
            version=self._version,
            dimensions=dimensions,
            vectors=vectors,
        )

    async def close(self) -> None:
        await self._client.aclose()
