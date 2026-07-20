import asyncio
import json
import time
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ValidationError

from mezo_control_plane.core.domain import ModelMessage, ModelRequest, ModelResponse
from mezo_control_plane.core.errors import ProviderUnavailable
from mezo_control_plane.providers.base import ModelProvider, ProviderError, ProviderFailureType


class ModelRole(StrEnum):
    FAST = "fast"
    PLANNER = "planner"
    EXECUTOR = "executor"
    BLIND_REVIEWER = "blind_reviewer"
    REVIEWER = "blind_reviewer"
    SECURITY_REVIEWER = "security_reviewer"
    FINAL_VERIFIER = "final_verifier"
    FALLBACK = "fallback"


@dataclass(frozen=True)
class Route:
    provider: ModelProvider
    model: str
    input_cost_per_million: float = 0
    output_cost_per_million: float = 0
    token_budget: int = 65_536


@dataclass(frozen=True)
class AttemptEvidence:
    role: ModelRole
    provider: str
    model: str
    started_at: float
    latency_seconds: float
    outcome: str
    failure_type: str | None
    input_tokens: int
    output_tokens: int
    cost_usd: float


@dataclass(frozen=True)
class BlindReviewContext:
    original_task: str
    repository_rules: str
    approved_plan: str
    diff: str
    changed_files: tuple[str, ...]
    test_evidence: str
    guard_receipts: str
    risk_policy: str

    def request(self) -> ModelRequest:
        payload = {
            "original_task": self.original_task,
            "repository_rules": self.repository_rules,
            "approved_plan": self.approved_plan,
            "diff": self.diff,
            "changed_files": self.changed_files,
            "test_evidence": self.test_evidence,
            "guard_receipts": self.guard_receipts,
            "risk_policy": self.risk_policy,
        }
        return ModelRequest(
            system_instruction="Perform an independent blind review using only supplied evidence.",
            messages=[ModelMessage(role="user", content=json.dumps(payload, sort_keys=True))],
        )


class ModelRouter:
    def __init__(self, routes: dict[ModelRole, list[Route]], max_retries: int = 0) -> None:
        self._routes = routes
        self._max_retries = max_retries
        self.attempts: list[AttemptEvidence] = []
        self.total_cost_usd = 0.0
        self._validate()

    def _validate(self) -> None:
        for role, routes in self._routes.items():
            if not routes:
                raise ValueError(f"Route {role.value} has no candidates")
            for route in routes:
                models = getattr(route.provider, "models", None)
                if models is not None and route.model not in models:
                    raise ValueError(
                        f"Unknown model {route.model} for provider {route.provider.name}"
                    )

    async def generate(
        self,
        role: ModelRole,
        request: ModelRequest,
        *,
        deadline_seconds: float | None = None,
        cancellation: asyncio.Event | None = None,
        response_model: type[BaseModel] | None = None,
    ) -> ModelResponse:
        failures: list[str] = []
        budget_exhausted = False
        started_route = time.monotonic()
        for route in self._routes.get(role, []):
            if request.max_output_tokens > route.token_budget:
                budget_exhausted = True
                failures.append(f"{route.provider.name}/{route.model}: token budget exceeded")
                continue
            for attempt in range(self._max_retries + 1):
                if cancellation and cancellation.is_set():
                    raise ProviderError(
                        ProviderFailureType.CANCELLATION, "Routing cancelled", retryable=False
                    )
                remaining = None
                if deadline_seconds is not None:
                    remaining = deadline_seconds - (time.monotonic() - started_route)
                    if remaining <= 0:
                        raise ProviderError(
                            ProviderFailureType.TIMEOUT, "Routing deadline exceeded", retryable=True
                        )
                attempt_started = time.monotonic()
                try:
                    response = await route.provider.generate(
                        request,
                        route.model,
                        deadline_seconds=remaining,
                        cancellation=cancellation,
                    )
                    if response_model is not None:
                        try:
                            structured = response_model.model_validate_json(response.text)
                        except (ValidationError, ValueError) as error:
                            raise ProviderError(
                                ProviderFailureType.MALFORMED_OUTPUT,
                                "Structured provider output failed validation",
                                retryable=False,
                            ) from error
                        response = response.model_copy(
                            update={"structured_output": structured.model_dump()}
                        )
                    cost = (
                        response.input_tokens * route.input_cost_per_million
                        + response.output_tokens * route.output_cost_per_million
                    ) / 1_000_000
                    self.total_cost_usd += cost
                    self.attempts.append(
                        AttemptEvidence(
                            role,
                            route.provider.name,
                            route.model,
                            attempt_started,
                            time.monotonic() - attempt_started,
                            "success",
                            None,
                            response.input_tokens,
                            response.output_tokens,
                            cost,
                        )
                    )
                    return response
                except ProviderError as error:
                    failures.append(
                        f"{route.provider.name}/{route.model}: {error.failure_type.value}"
                    )
                    self.attempts.append(
                        AttemptEvidence(
                            role,
                            route.provider.name,
                            route.model,
                            attempt_started,
                            time.monotonic() - attempt_started,
                            "failure",
                            error.failure_type.value,
                            0,
                            0,
                            0,
                        )
                    )
                    if not error.retryable or attempt >= self._max_retries:
                        break
                except ProviderUnavailable:
                    failures.append(f"{route.provider.name}/{route.model}: unavailable")
                    if attempt >= self._max_retries:
                        break
        raise ProviderError(
            ProviderFailureType.BUDGET_EXHAUSTED
            if budget_exhausted
            else ProviderFailureType.SERVER,
            "; ".join(failures) or f"No route available for {role.value}",
            retryable=True,
        )
