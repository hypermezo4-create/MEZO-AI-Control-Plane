from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from typing import TypeVar
from uuid import uuid4

from pydantic import BaseModel

from mezo_control_plane.agents.contracts import (
    AgentExecutionRecord,
    AgentLimits,
    AgentRole,
)
from mezo_control_plane.core.domain import ModelMessage, ModelRequest
from mezo_control_plane.model_router.router import ModelRole, ModelRouter

OutputT = TypeVar("OutputT", bound=BaseModel)


class AgentBudgetExceeded(RuntimeError):
    pass


class TypedAgent:
    def __init__(
        self,
        *,
        role: AgentRole,
        prompt: str,
        prompt_version: str,
        limits: AgentLimits,
        router: ModelRouter,
    ) -> None:
        self.role = role
        self.prompt = prompt
        self.prompt_version = prompt_version
        self.limits = limits
        self._router = router
        self._model_calls = 0

    async def invoke(
        self,
        task_id: str,
        input_model: BaseModel,
        output_type: type[OutputT],
        *,
        cancellation: asyncio.Event | None = None,
    ) -> tuple[OutputT, AgentExecutionRecord]:
        if self._model_calls >= self.limits.max_model_calls:
            raise AgentBudgetExceeded(f"{self.role.value} model-call budget exhausted")
        if cancellation and cancellation.is_set():
            raise asyncio.CancelledError
        payload = input_model.model_dump_json()
        started = datetime.now(UTC)
        self._model_calls += 1
        response = await self._router.generate(
            ModelRole(self.role.value),
            ModelRequest(
                system_instruction=self.prompt,
                messages=[ModelMessage(role="user", content=payload)],
                max_output_tokens=self.limits.max_tokens,
            ),
            deadline_seconds=self.limits.deadline_seconds,
            cancellation=cancellation,
            response_model=output_type,
        )
        output = output_type.model_validate(response.structured_output)
        record = AgentExecutionRecord(
            invocation_id=str(uuid4()),
            task_id=task_id,
            role=self.role,
            prompt_version=self.prompt_version,
            provider=response.provider,
            model=response.model,
            input_hash=hashlib.sha256(payload.encode()).hexdigest(),
            output_hash=hashlib.sha256(output.model_dump_json().encode()).hexdigest(),
            model_calls=1,
            tool_calls=0,
            started_at=started,
            completed_at=datetime.now(UTC),
        )
        return output, record


def export_agent_schema(
    input_type: type[BaseModel], output_type: type[BaseModel]
) -> dict[str, object]:
    return {"input": input_type.model_json_schema(), "output": output_type.model_json_schema()}
