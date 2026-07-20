import hashlib
import hmac

from fastapi import APIRouter, Header, HTTPException, Request, status

from mezo_control_plane.api.dependencies import ServiceDependency, SettingsDependency
from mezo_control_plane.api.schemas import ModelResponseSchema, ProviderResponse, RepositoryResponse

router = APIRouter(prefix="/v1", tags=["control"])


@router.get("/repositories", response_model=list[RepositoryResponse])
async def repositories(
    service: ServiceDependency,
) -> list[RepositoryResponse]:
    page = await service.list_tasks(0, 200)
    names = sorted({task.request.repository for task in page.items})
    return [RepositoryResponse(id=name, full_name=name) for name in names]


@router.get("/repositories/{repository_id:path}", response_model=RepositoryResponse)
async def repository(
    repository_id: str,
    service: ServiceDependency,
) -> RepositoryResponse:
    items = await repositories(service)
    for item in items:
        if item.id == repository_id:
            return item
    raise HTTPException(status_code=404, detail="Repository not found")


@router.get("/providers", response_model=list[ProviderResponse])
async def providers(settings: SettingsDependency) -> list[ProviderResponse]:
    return [
        ProviderResponse(
            id="gemini-a", healthy=bool(settings.gemini_api_key_primary.get_secret_value())
        ),
        ProviderResponse(
            id="gemini-b", healthy=bool(settings.gemini_api_key_secondary.get_secret_value())
        ),
        ProviderResponse(id="qwen", healthy=bool(settings.qwen_base_url)),
    ]


@router.get("/models", response_model=list[ModelResponseSchema])
async def models(settings: SettingsDependency) -> list[ModelResponseSchema]:
    return [
        ModelResponseSchema(provider="gemini-a", model=settings.gemini_primary_model, enabled=True),
        ModelResponseSchema(provider="gemini-b", model=settings.gemini_review_model, enabled=True),
        ModelResponseSchema(
            provider="qwen", model=settings.qwen_model, enabled=bool(settings.qwen_base_url)
        ),
    ]


@router.post("/webhooks/github", status_code=status.HTTP_202_ACCEPTED)
async def github_webhook(
    request: Request,
    settings: SettingsDependency,
    signature: str = Header(default="", alias="X-Hub-Signature-256"),
) -> dict[str, str]:
    secret = settings.github_webhook_secret.get_secret_value()
    body = await request.body()
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not secret or not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    return {"status": "accepted"}
