import httpx
import pytest
from fastapi import FastAPI

import mezo_control_plane.api.middleware as api_middleware
from mezo_control_plane.api.middleware import AuthenticationMiddleware, RequestIdMiddleware


async def test_authentication_middleware_uses_constant_time_comparison(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[tuple[str, str]] = []

    def compare(left: str, right: str) -> bool:
        called.append((left, right))
        return False

    monkeypatch.setattr(api_middleware.secrets, "compare_digest", compare)
    app = FastAPI()

    @app.get("/protected")
    async def protected() -> dict[str, str]:
        return {"status": "ok"}

    app.add_middleware(AuthenticationMiddleware, api_key="expected-key")
    app.add_middleware(RequestIdMiddleware)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/protected", headers={"x-api-key": "wrong-key"})
    assert response.status_code == 401
    assert called == [("wrong-key", "expected-key")]
