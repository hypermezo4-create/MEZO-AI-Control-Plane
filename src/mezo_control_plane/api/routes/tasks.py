from uuid import UUID

from fastapi import APIRouter, Header, Query, status

from mezo_control_plane.api.dependencies import ServiceDependency
from mezo_control_plane.api.schemas import (
    ActionResponse,
    CancellationRequest,
    DecisionRequest,
    EvidenceResponse,
    PageResponse,
    TaskCreateResponse,
    ValidationResponse,
)
from mezo_control_plane.core.domain import TaskRecord, TaskRequest
from mezo_control_plane.observability.reports import TaskReport

router = APIRouter(prefix="/v1/tasks", tags=["tasks"])


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TaskCreateResponse,
    responses={409: {"description": "Conflicting submission"}},
)
async def submit_task(
    request: TaskRequest,
    service: ServiceDependency,
    idempotency_key: str = Header(min_length=8, max_length=255, alias="Idempotency-Key"),
) -> TaskCreateResponse:
    task, result = await service.create_task(request, idempotency_key)
    return TaskCreateResponse(task=task, accepted=result.accepted, duplicate=not result.accepted)


@router.post("/validate", response_model=ValidationResponse)
async def validate_task(
    request: TaskRequest,
    service: ServiceDependency,
) -> ValidationResponse:
    return ValidationResponse(request=await service.validate_task(request))


@router.get("", response_model=PageResponse[TaskRecord])
async def list_tasks(
    service: ServiceDependency,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> PageResponse[TaskRecord]:
    page = await service.list_tasks(offset, limit)
    return PageResponse(items=page.items, total=page.total, offset=offset, limit=limit)


@router.get("/{task_id}", response_model=TaskRecord)
async def get_task(
    task_id: UUID,
    service: ServiceDependency,
) -> TaskRecord:
    return await service.get_task(task_id)


@router.post("/{task_id}/cancel", response_model=ActionResponse)
async def cancel_task(
    task_id: UUID,
    request: CancellationRequest,
    service: ServiceDependency,
) -> ActionResponse:
    result = await service.cancel_task(task_id, "api", request.reason)
    return ActionResponse(status=result.value, task=await service.get_task(task_id))


@router.post("/{task_id}/retry", response_model=ActionResponse)
async def retry_task(
    task_id: UUID,
    service: ServiceDependency,
) -> ActionResponse:
    return ActionResponse(status="queued", task=await service.retry_task(task_id))


@router.get("/{task_id}/evidence", response_model=EvidenceResponse)
async def evidence(
    task_id: UUID,
    service: ServiceDependency,
) -> EvidenceResponse:
    return EvidenceResponse(items=await service.evidence(task_id))


@router.get("/{task_id}/report", response_model=TaskReport)
async def report(task_id: UUID, service: ServiceDependency) -> TaskReport:
    return await service.report(task_id)


@router.get("/{task_id}/reviews")
async def reviews(
    task_id: UUID,
    service: ServiceDependency,
) -> dict[str, object]:
    await service.get_task(task_id)
    return {"items": []}


@router.post("/{task_id}/approvals", response_model=ActionResponse)
async def approve(
    task_id: UUID,
    request: DecisionRequest,
    service: ServiceDependency,
) -> ActionResponse:
    return ActionResponse(status="approved", task=await service.decide(task_id, True))


@router.post("/{task_id}/rejections", response_model=ActionResponse)
async def reject(
    task_id: UUID,
    request: DecisionRequest,
    service: ServiceDependency,
) -> ActionResponse:
    return ActionResponse(status="rejected", task=await service.decide(task_id, False))
