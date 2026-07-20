from __future__ import annotations

import hashlib
import json

from mezo_control_plane.sandbox.manager import CommandRunner, StructuredCommand
from mezo_control_plane.tools.contracts import (
    ApplyPatchInput,
    CommandInput,
    GitInspectionInput,
    ListDirectoryInput,
    PreparePullRequestInput,
    ReadFileInput,
    SearchCodeInput,
    ToolRisk,
)
from mezo_control_plane.tools.filesystem import FilesystemTools
from mezo_control_plane.tools.registry import RegisteredTool, ToolRegistry


class BuiltinToolSet:
    def __init__(self, files: FilesystemTools, commands: CommandRunner) -> None:
        self._files = files
        self._commands = commands

    def registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(
            RegisteredTool(
                "read_file",
                "1",
                ReadFileInput,
                ToolRisk.READ,
                "workspace:read",
                False,
                False,
                self._files.read_file,
            )
        )
        registry.register(
            RegisteredTool(
                "list_directory",
                "1",
                ListDirectoryInput,
                ToolRisk.READ,
                "workspace:read",
                False,
                False,
                self._files.list_directory,
            )
        )
        registry.register(
            RegisteredTool(
                "search_code",
                "1",
                SearchCodeInput,
                ToolRisk.READ,
                "workspace:read",
                False,
                False,
                self._files.search_code,
            )
        )
        registry.register(
            RegisteredTool(
                "apply_patch",
                "1",
                ApplyPatchInput,
                ToolRisk.WRITE,
                "workspace:write",
                True,
                False,
                self._files.apply_patch,
            )
        )
        registry.register(
            RegisteredTool(
                "run_command",
                "1",
                CommandInput,
                ToolRisk.EXECUTE,
                "command:execute",
                True,
                False,
                self.run_command,
            )
        )
        registry.register(
            RegisteredTool(
                "run_tests",
                "1",
                CommandInput,
                ToolRisk.EXECUTE,
                "tests:execute",
                False,
                False,
                self.run_command,
            )
        )
        registry.register(
            RegisteredTool(
                "git_status",
                "1",
                GitInspectionInput,
                ToolRisk.READ,
                "workspace:read",
                False,
                False,
                self.git_status,
            )
        )
        registry.register(
            RegisteredTool(
                "git_diff",
                "1",
                GitInspectionInput,
                ToolRisk.READ,
                "workspace:read",
                False,
                False,
                self.git_diff,
            )
        )
        registry.register(
            RegisteredTool(
                "prepare_pull_request",
                "1",
                PreparePullRequestInput,
                ToolRisk.DELIVERY,
                "pull_request:prepare",
                True,
                False,
                self.prepare_pull_request,
            )
        )
        return registry

    async def run_command(self, value: CommandInput) -> object:
        result = await self._commands.run(
            StructuredCommand(
                value.executable,
                value.arguments,
                value.working_directory,
                timeout_seconds=value.timeout_seconds,
                output_limit=value.output_limit,
            )
        )
        return {
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "truncated": result.truncated,
            "duration_seconds": result.duration_seconds,
        }

    async def git_status(self, value: GitInspectionInput) -> object:
        return await self.run_command(
            CommandInput(
                executable="git",
                arguments=("status", "--short"),
                working_directory=value.working_directory,
            )
        )

    async def git_diff(self, value: GitInspectionInput) -> object:
        return await self.run_command(
            CommandInput(
                executable="git",
                arguments=("diff", "--no-ext-diff", "--"),
                working_directory=value.working_directory,
            )
        )

    async def prepare_pull_request(self, value: PreparePullRequestInput) -> object:
        payload = value.model_dump()
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return {"payload": payload, "payload_hash": hashlib.sha256(body.encode()).hexdigest()}
