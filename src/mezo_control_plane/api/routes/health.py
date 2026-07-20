from dataclasses import asdict

from fastapi import APIRouter, Request, Response, status

from mezo_control_plane.api.dependencies import ServiceDependency

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "live"}


@router.get("/health/ready")
async def ready(
    response: Response,
    service: ServiceDependency,
) -> dict[str, object]:
    checks = await service.readiness()
    healthy = all(checks.values())
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if healthy else "not_ready", "checks": checks}


@router.get("/metrics")
async def metrics(request: Request) -> dict[str, object]:
    collector = getattr(request.app.state, "metrics", None)
    if collector is None:
        return {"status": "unavailable"}
    snapshot: dict[str, object] = asdict(await collector.snapshot())
    return snapshot
