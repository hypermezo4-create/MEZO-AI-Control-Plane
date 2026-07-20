import pytest
from pydantic import BaseModel

from mezo_control_plane.tools.contracts import ToolCallRequest, ToolRisk
from mezo_control_plane.tools.registry import RegisteredTool, ToolRegistry


class EchoInput(BaseModel):
    value: str


async def echo(value: EchoInput) -> object:
    return {"value": value.value}


@pytest.mark.asyncio
async def test_tool_registry_validates_permission_approval_and_schema() -> None:
    registry = ToolRegistry()
    registry.register(
        RegisteredTool(
            "echo",
            "1",
            EchoInput,
            ToolRisk.WRITE,
            "workspace:write",
            True,
            False,
            echo,
        )
    )
    request = ToolCallRequest(name="echo", version="1", arguments={"value": "ok"})
    with pytest.raises(PermissionError, match="permission"):
        await registry.execute(request, permissions=frozenset())
    with pytest.raises(PermissionError, match="approval"):
        await registry.execute(request, permissions=frozenset({"workspace:write"}))
    result, evidence = await registry.execute(
        request.model_copy(update={"approval_id": "approval-1"}),
        permissions=frozenset({"workspace:write"}),
    )
    assert result == {"value": "ok"}
    assert evidence.success


def test_duplicate_and_unknown_tool_are_rejected() -> None:
    registry = ToolRegistry()
    tool = RegisteredTool(
        "echo", "1", EchoInput, ToolRisk.READ, "workspace:read", False, False, echo
    )
    registry.register(tool)
    with pytest.raises(ValueError, match="Duplicate"):
        registry.register(tool)
