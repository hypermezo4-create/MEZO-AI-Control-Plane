import asyncio
import json
from pathlib import Path
from typing import cast

import httpx
import pytest
from pydantic import BaseModel

from mezo_control_plane.core.domain import ModelMessage, ModelRequest, ModelResponse
from mezo_control_plane.model_router.configuration import load_router
from mezo_control_plane.model_router.router import (
    BlindReviewContext,
    ModelRole,
    ModelRouter,
    Route,
)
from mezo_control_plane.providers.base import (
    ModelProvider,
    ProviderError,
    ProviderFailureType,
)
from mezo_control_plane.providers.embeddings import OpenAICompatibleEmbeddings
from mezo_control_plane.providers.gemini import GeminiProvider
from mezo_control_plane.providers.qwen import QwenProvider
from mezo_control_plane.providers.resilience import CircuitBreaker, CircuitState
from mezo_control_plane.worker.failure_classification import FailureClass, classify_failure


def request(maximum: int = 128) -> ModelRequest:
    return ModelRequest(
        messages=[ModelMessage(role="user", content="hello")], max_output_tokens=maximum
    )


def gemini_body(text: str = "ok") -> dict[str, object]:
    return {
        "candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
    }


def gemini(handler: httpx.MockTransport, **kwargs: object) -> GeminiProvider:
    return GeminiProvider(
        "gemini-a",
        "key",
        "project-a",
        frozenset({"gemini-pro"}),
        client=httpx.AsyncClient(transport=handler, base_url="https://gemini.test"),
        retry_budget=cast(int, kwargs.pop("retry_budget", 0)),
        **kwargs,
    )


async def test_gemini_success_usage_and_independent_project_header() -> None:
    seen: list[str] = []

    def handler(incoming: httpx.Request) -> httpx.Response:
        seen.append(incoming.headers["x-goog-user-project"])
        return httpx.Response(200, json=gemini_body(), headers={"x-request-id": "gemini-1"})

    provider = gemini(httpx.MockTransport(handler))
    response = await provider.generate(request(), "gemini-pro")
    assert response.text == "ok"
    assert (response.input_tokens, response.output_tokens) == (10, 5)
    assert seen == ["project-a"]


async def test_gemini_rate_limit_retry_after_and_router_fallback() -> None:
    limited = gemini(
        httpx.MockTransport(lambda request: httpx.Response(429, headers={"Retry-After": "7"}))
    )
    qwen = QwenProvider(
        "https://qwen.test/v1",
        "key",
        frozenset({"qwen-coder"}),
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={
                        "choices": [{"message": {"content": "fallback"}}],
                        "usage": {},
                    },
                )
            )
        ),
    )
    with pytest.raises(ProviderError) as raised:
        await limited.generate(request(), "gemini-pro")
    assert raised.value.failure_type is ProviderFailureType.RATE_LIMIT
    assert raised.value.retry_after_seconds == 7
    router = ModelRouter(
        {ModelRole.PLANNER: [Route(limited, "gemini-pro"), Route(qwen, "qwen-coder")]}
    )
    assert (await router.generate(ModelRole.PLANNER, request())).text == "fallback"


@pytest.mark.parametrize(
    "status,failure", [(401, "authentication"), (403, "permission"), (500, "server")]
)
async def test_gemini_http_failure_classification(status: int, failure: str) -> None:
    provider = gemini(httpx.MockTransport(lambda request: httpx.Response(status)))
    with pytest.raises(ProviderError) as raised:
        await provider.generate(request(), "gemini-pro")
    assert raised.value.failure_type.value == failure


async def test_gemini_malformed_content_policy_timeout_and_cancellation() -> None:
    malformed = gemini(httpx.MockTransport(lambda request: httpx.Response(200, json={})))
    with pytest.raises(ProviderError) as raised:
        await malformed.generate(request(), "gemini-pro")
    assert raised.value.failure_type is ProviderFailureType.MALFORMED_OUTPUT
    safety_body = {"candidates": [{"finishReason": "SAFETY", "content": {"parts": []}}]}
    blocked = gemini(httpx.MockTransport(lambda request: httpx.Response(200, json=safety_body)))
    with pytest.raises(ProviderError) as raised:
        await blocked.generate(request(), "gemini-pro")
    assert raised.value.failure_type is ProviderFailureType.CONTENT_POLICY

    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.02)
        return httpx.Response(200, json=gemini_body())

    timed = gemini(httpx.MockTransport(slow), timeout_seconds=0.001)
    with pytest.raises(ProviderError) as raised:
        await timed.generate(request(), "gemini-pro")
    assert raised.value.failure_type is ProviderFailureType.TIMEOUT
    cancelled = asyncio.Event()
    cancelled.set()
    with pytest.raises(ProviderError) as raised:
        await malformed.generate(request(), "gemini-pro", cancellation=cancelled)
    assert raised.value.failure_type is ProviderFailureType.CANCELLATION


async def test_provider_concurrency_limit_and_circuit_recovery() -> None:
    active = 0
    maximum = 0
    release = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await release.wait()
        active -= 1
        return httpx.Response(200, json=gemini_body())

    provider = gemini(httpx.MockTransport(handler), concurrency=1)
    first = asyncio.create_task(provider.generate(request(), "gemini-pro"))
    second = asyncio.create_task(provider.generate(request(), "gemini-pro"))
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(first, second)
    assert maximum == 1
    circuit = CircuitBreaker(failure_threshold=1, recovery_seconds=5)
    circuit.failure(now=10)
    assert circuit.state is CircuitState.OPEN and not circuit.allow(now=12)
    assert circuit.allow(now=15) and circuit.state is CircuitState.HALF_OPEN
    circuit.success()
    assert circuit.state is CircuitState.CLOSED


async def test_qwen_tool_calls_models_and_invalid_output() -> None:
    def handler(incoming: httpx.Request) -> httpx.Response:
        if incoming.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "qwen-coder"}]})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [{"id": "call", "function": {"name": "test"}}],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            },
        )

    provider = QwenProvider(
        "https://qwen.test/v1",
        "key",
        frozenset({"qwen-coder"}),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    response = await provider.generate(request(), "qwen-coder")
    assert response.tool_calls[0]["id"] == "call"
    assert await provider.healthy()
    invalid = QwenProvider(
        "https://qwen.test/v1",
        "key",
        frozenset({"qwen-coder"}),
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))
        ),
    )
    with pytest.raises(ProviderError) as raised:
        await invalid.generate(request(), "qwen-coder")
    assert raised.value.failure_type is ProviderFailureType.MALFORMED_OUTPUT


async def test_embeddings_are_validated_without_fake_fallback() -> None:
    provider = OpenAICompatibleEmbeddings(
        "qwen",
        "https://qwen.test/v1",
        "key",
        "embed-v1",
        "2026-01",
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={"data": [{"index": 0, "embedding": [0.1, 0.2]}]},
                )
            )
        ),
    )
    batch = await provider.embed(["input"])
    assert batch.dimensions == 2 and batch.version == "2026-01"
    with pytest.raises(ValueError):
        await provider.embed([])


class Structured(BaseModel):
    approved: bool


class StaticProvider:
    name = "static"
    models = frozenset({"model"})

    def __init__(self, text: str = '{"approved":true}') -> None:
        self.text = text

    async def generate(
        self,
        request: ModelRequest,
        model: str,
        *,
        deadline_seconds: float | None = None,
        cancellation: asyncio.Event | None = None,
    ) -> ModelResponse:
        return ModelResponse(
            provider=self.name,
            model=model,
            text=self.text,
            input_tokens=100,
            output_tokens=50,
        )

    async def healthy(self) -> bool:
        return True


async def test_router_structured_output_token_budget_cost_and_no_route() -> None:
    provider = StaticProvider()
    router = ModelRouter(
        {
            ModelRole.FINAL_VERIFIER: [
                Route(provider, "model", input_cost_per_million=1, output_cost_per_million=2)
            ]
        }
    )
    response = await router.generate(ModelRole.FINAL_VERIFIER, request(), response_model=Structured)
    assert response.structured_output == {"approved": True}
    assert router.total_cost_usd == 0.0002
    budgeted = ModelRouter({ModelRole.FAST: [Route(provider, "model", token_budget=64)]})
    with pytest.raises(ProviderError):
        await budgeted.generate(ModelRole.FAST, request(128))
    with pytest.raises(ProviderError):
        await ModelRouter({ModelRole.FAST: [Route(StaticProvider("bad"), "model")]}).generate(
            ModelRole.FAST, request(), response_model=Structured
        )


def test_blind_review_context_excludes_executor_persuasion() -> None:
    context = BlindReviewContext(
        "task",
        "rules",
        "plan",
        "diff",
        ("file.py",),
        "tests",
        "guards",
        "risk",
    )
    encoded = context.request().messages[0].content
    assert "executor_confidence" not in encoded
    assert "implementation_narrative" not in encoded
    assert json.loads(encoded)["approved_plan"] == "plan"


def test_provider_failures_map_to_worker_retry_and_permanent_decisions() -> None:
    limited = classify_failure(
        ProviderError(
            ProviderFailureType.RATE_LIMIT,
            "limited",
            retryable=True,
            retry_after_seconds=12,
        )
    )
    assert limited.classification is FailureClass.RATE_LIMITED
    assert limited.retry_after_seconds == 12
    denied = classify_failure(
        ProviderError(ProviderFailureType.PERMISSION, "denied", retryable=False)
    )
    assert denied.classification is FailureClass.PERMANENT_AUTHORIZATION
    assert not denied.retryable


def test_startup_rejects_unknown_provider_and_model(tmp_path: Path) -> None:
    unknown_provider = tmp_path / "unknown-provider.yaml"
    unknown_provider.write_text(
        "version: 1\nroutes:\n  fast:\n    - {provider: missing, model: model}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Unknown provider"):
        load_router(unknown_provider, {"static": cast(ModelProvider, StaticProvider())})
    unknown_model = tmp_path / "unknown-model.yaml"
    routes = "\n".join(
        f"  {role.value}:\n    - {{provider: static, model: unknown}}" for role in ModelRole
    )
    unknown_model.write_text(f"version: 1\nroutes:\n{routes}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Unknown model"):
        load_router(unknown_model, {"static": cast(ModelProvider, StaticProvider())})
