from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ToolRisk(StrEnum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    DELIVERY = "delivery"


class ToolCallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    version: str
    arguments: dict[str, Any]
    approval_id: str | None = None


class ToolEvidence(BaseModel):
    tool: str
    version: str
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    summary: str
    success: bool


class ReadFileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    max_bytes: int = Field(default=200_000, ge=1, le=2_000_000)


class ListDirectoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = "."
    limit: int = Field(default=500, ge=1, le=5000)


class SearchCodeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=500)
    path: str = "."
    limit: int = Field(default=100, ge=1, le=1000)


class StructuredPatchFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    base_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    content: str | None
    delete: bool = False


class ApplyPatchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    files: tuple[StructuredPatchFile, ...] = Field(min_length=1, max_length=100)
    approved_protected_write: bool = False


class CommandInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    executable: str
    arguments: tuple[str, ...]
    working_directory: str = "."
    timeout_seconds: float = Field(default=300, gt=0, le=1800)
    output_limit: int = Field(default=1_000_000, ge=1, le=10_000_000)


class GitInspectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    working_directory: str = "."


class PreparePullRequestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_summary: str
    base_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    head_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    changed_files: tuple[str, ...]
    test_evidence: tuple[str, ...]
    guard_receipts: tuple[str, ...]
    risk_decisions: tuple[str, ...]
    approvals: tuple[str, ...]
    known_limitations: tuple[str, ...]
    rollback_plan: str
