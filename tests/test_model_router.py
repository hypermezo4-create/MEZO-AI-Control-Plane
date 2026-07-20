from mezo_control_plane.core.domain import ModelRequest, ModelResponse
from mezo_control_plane.core.errors import ProviderUnavailable
from mezo_control_plane.model_router.router import ModelRole, ModelRouter, Route


class FailingProvider:
    name = "failing"
    models = frozenset({"first"})

    async def generate(
        self,
        request: ModelRequest,
        model: str,
        *,
        deadline_seconds: float | None = None,
        cancellation: object = None,
    ) -> ModelResponse:
        raise ProviderUnavailable("unavailable")

    async def healthy(self) -> bool:
        return False


class WorkingProvider:
    name = "working"
    models = frozenset({"second"})

    async def generate(
        self,
        request: ModelRequest,
        model: str,
        *,
        deadline_seconds: float | None = None,
        cancellation: object = None,
    ) -> ModelResponse:
        return ModelResponse(provider=self.name, model=model, text="ok")

    async def healthy(self) -> bool:
        return True


async def test_router_fails_over_to_next_provider() -> None:
    router = ModelRouter(
        {
            ModelRole.PLANNER: [
                Route(FailingProvider(), "first"),
                Route(WorkingProvider(), "second"),
            ]
        },
        max_retries=0,
    )
    response = await router.generate(ModelRole.PLANNER, ModelRequest(messages=[]))
    assert response.provider == "working"
    assert response.model == "second"
