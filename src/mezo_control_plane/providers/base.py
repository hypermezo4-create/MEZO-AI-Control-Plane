from typing import Protocol

from mezo_control_plane.core.domain import ModelRequest, ModelResponse


class ModelProvider(Protocol):
    name: str

    async def generate(self, request: ModelRequest, model: str) -> ModelResponse: ...

    async def healthy(self) -> bool: ...
