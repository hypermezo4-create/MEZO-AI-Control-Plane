from pathlib import Path

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, Field

from mezo_control_plane.model_router.router import ModelRole, ModelRouter, Route
from mezo_control_plane.providers.base import ModelProvider


class RouteCandidateConfig(BaseModel):
    provider: str
    model: str
    input_cost_per_million: float = Field(default=0, ge=0)
    output_cost_per_million: float = Field(default=0, ge=0)
    token_budget: int = Field(default=65_536, gt=0)


class RoutingConfig(BaseModel):
    version: int = Field(ge=1)
    routes: dict[ModelRole, list[RouteCandidateConfig]]


def load_router(path: Path, providers: dict[str, ModelProvider]) -> ModelRouter:
    config = RoutingConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    routes: dict[ModelRole, list[Route]] = {}
    for role, candidates in config.routes.items():
        routes[role] = []
        for candidate in candidates:
            provider = providers.get(candidate.provider)
            if provider is None:
                raise ValueError(f"Unknown provider {candidate.provider} in routing configuration")
            routes[role].append(
                Route(
                    provider,
                    candidate.model,
                    candidate.input_cost_per_million,
                    candidate.output_cost_per_million,
                    candidate.token_budget,
                )
            )
    missing = set(ModelRole) - set(routes)
    if missing:
        omitted = sorted(item.value for item in missing)
        raise ValueError(f"Routing configuration omits roles: {omitted}")
    return ModelRouter(routes)
