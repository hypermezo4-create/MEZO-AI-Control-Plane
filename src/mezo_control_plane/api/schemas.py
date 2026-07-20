from pydantic import BaseModel, Field

from mezo_control_plane.core.domain import EvidenceItem, TaskRecord, TaskRequest


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str


class ErrorEnvelope(BaseModel):
    error: ErrorDetail


class PageResponse[T](BaseModel):
    items: list[T]
    total: int
    offset: int
    limit: int


class TaskCreateResponse(BaseModel):
    task: TaskRecord
    accepted: bool
    duplicate: bool


class ValidationResponse(BaseModel):
    valid: bool = True
    request: TaskRequest


class CancellationRequest(BaseModel):
    reason: str = Field(default="cancelled by API request", min_length=1, max_length=1_000)


class DecisionRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1_000)


class ActionResponse(BaseModel):
    status: str
    task: TaskRecord | None = None


class EvidenceResponse(BaseModel):
    items: list[EvidenceItem]


class RepositoryResponse(BaseModel):
    id: str
    full_name: str
    enabled: bool = True


class ProviderResponse(BaseModel):
    id: str
    healthy: bool


class ModelResponseSchema(BaseModel):
    provider: str
    model: str
    enabled: bool
