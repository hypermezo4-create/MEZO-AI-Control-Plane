from fastapi import APIRouter, Request, Response, status
from fastapi.responses import PlainTextResponse

from mezo_control_plane.api.dependencies import ServiceDependency
from mezo_control_plane.observability.metrics import render_prometheus

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


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics(request: Request) -> PlainTextResponse:
    queue_collector = getattr(request.app.state, "queue_metrics", None)
    queue_snapshot = None
    if queue_collector is not None:
        try:
            queue_snapshot = await queue_collector.snapshot()
        except Exception:
            queue_snapshot = None
    body = render_prometheus(request.app.state.application_metrics.snapshot(), queue_snapshot)
    return PlainTextResponse(body, media_type="text/plain; version=0.0.4; charset=utf-8")
