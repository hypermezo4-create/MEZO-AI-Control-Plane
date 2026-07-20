from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum

from mezo_control_plane.core.domain import ModelRequest, ModelResponse
from mezo_control_plane.core.errors import ProviderUnavailable
from mezo_control_plane.providers.base import ModelProvider


class ModelRole(StrEnum):
    FAST = "fast"
    PLANNER = "planner"
    EXECUTOR = "executor"
    REVIEWER = "reviewer"
    FALLBACK = "fallback"


@dataclass(frozen=True)
class Route:
    provider: ModelProvider
    model: str


class ModelRouter:
    def __init__(self, routes: dict[ModelRole, list[Route]], max_retries: int = 2) -> None:
        self._routes = routes
        self._max_retries = max_retries

    async def generate(self, role: ModelRole, request: ModelRequest) -> ModelResponse:
        failures: list[str] = []
        for route in self._routes.get(role, []):
            for attempt in range(self._max_retries + 1):
                try:
                    return await route.provider.generate(request, route.model)
                except ProviderUnavailable as exc:
                    failures.append(f"{route.provider.name}/{route.model}: {exc}")
                    if attempt < self._max_retries:
                        await asyncio.sleep(0.25 * (2**attempt))
        detail = "; ".join(failures) or f"No routes configured for role {role}"
        raise ProviderUnavailable(detail)
