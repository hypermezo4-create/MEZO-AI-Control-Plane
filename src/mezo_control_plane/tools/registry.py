from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel

from mezo_control_plane.tools.contracts import ToolCallRequest, ToolEvidence, ToolRisk


class ToolExecutor[InputT: BaseModel](Protocol):
    async def __call__(self, value: InputT) -> object: ...


@dataclass(frozen=True)
class RegisteredTool[InputT: BaseModel]:
    name: str
    version: str
    input_type: type[InputT]
    risk: ToolRisk
    required_permission: str
    approval_required: bool
    network_required: bool
    executor: ToolExecutor[InputT]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[tuple[str, str], RegisteredTool[Any]] = {}

    def register(self, tool: RegisteredTool[Any]) -> None:
        key = (tool.name, tool.version)
        if key in self._tools:
            raise ValueError(f"Duplicate tool registration: {tool.name}@{tool.version}")
        self._tools[key] = tool

    def registered(self) -> tuple[tuple[str, str], ...]:
        return tuple(sorted(self._tools))

    async def execute(
        self,
        request: ToolCallRequest,
        *,
        permissions: frozenset[str],
        network_allowed: bool = False,
    ) -> tuple[object, ToolEvidence]:
        tool = self._tools.get((request.name, request.version))
        if tool is None:
            raise LookupError("Unknown tool name or version")
        if tool.required_permission not in permissions:
            raise PermissionError("Tool permission denied")
        if tool.approval_required and not request.approval_id:
            raise PermissionError("Tool requires scoped approval")
        if tool.network_required and not network_allowed:
            raise PermissionError("Tool network requirement denied")
        validated = tool.input_type.model_validate(request.arguments)
        input_json = validated.model_dump_json()
        result = await tool.executor(validated)
        output_json = json.dumps(result, sort_keys=True, default=str)
        return result, ToolEvidence(
            tool=tool.name,
            version=tool.version,
            input_hash=hashlib.sha256(input_json.encode()).hexdigest(),
            output_hash=hashlib.sha256(output_json.encode()).hexdigest(),
            summary=f"{tool.name} returned {type(result).__name__}",
            success=True,
        )
