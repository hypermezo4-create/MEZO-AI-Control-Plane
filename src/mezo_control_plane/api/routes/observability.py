from dataclasses import asdict

from fastapi import APIRouter, Request

from mezo_control_plane.observability.alerts import evaluate_alerts, queue_metric_values

router = APIRouter(prefix="/v1/observability", tags=["observability"])


@router.get("/snapshot")
async def snapshot(request: Request) -> dict[str, object]:
    application_metrics = request.app.state.application_metrics.snapshot()
    queue_collector = getattr(request.app.state, "queue_metrics", None)
    queue_snapshot = await queue_collector.snapshot() if queue_collector is not None else None
    return {
        "application": asdict(application_metrics),
        "queue": asdict(queue_snapshot) if queue_snapshot is not None else None,
    }


@router.get("/alerts")
async def alerts(request: Request) -> dict[str, object]:
    queue_collector = getattr(request.app.state, "queue_metrics", None)
    values: dict[str, float] = {}
    if queue_collector is not None:
        values.update(queue_metric_values(await queue_collector.snapshot()))
    evaluations = evaluate_alerts(values)
    return {
        "firing": [item.model_dump(mode="json") for item in evaluations if item.firing],
        "evaluations": [item.model_dump(mode="json") for item in evaluations],
        "unavailable_metrics": [item.metric for item in evaluations if not item.available],
    }
