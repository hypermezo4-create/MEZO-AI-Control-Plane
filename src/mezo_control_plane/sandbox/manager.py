from __future__ import annotations

import asyncio
import os
import re
import signal
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from mezo_control_plane.sandbox.policies import FilesystemPolicy, SandboxPolicyError


class SandboxState(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    STOPPED = "stopped"
    DESTROYED = "destroyed"
    CLEANUP_FAILED = "cleanup_failed"


@dataclass(frozen=True)
class ResourcePolicy:
    cpu_count: float = 1
    memory_mb: int = 1024
    pid_limit: int = 128
    disk_mb: int = 2048
    output_bytes: int = 1_000_000


@dataclass
class SandboxRecord:
    sandbox_id: str
    task_id: str
    repository_id: str
    base_sha: str
    workspace: Path
    evidence_directory: Path
    resources: ResourcePolicy
    created_at: datetime
    expires_at: datetime
    state: SandboxState = SandboxState.CREATED
    cleanup_status: str = "pending"


@dataclass(frozen=True)
class StructuredCommand:
    executable: str
    arguments: tuple[str, ...]
    working_directory: str = "."
    environment: tuple[tuple[str, str], ...] = ()
    timeout_seconds: float = 300
    stdin: bytes | None = None
    output_limit: int = 1_000_000
    network_required: bool = False


@dataclass(frozen=True)
class ProcessResult:
    exit_code: int
    stdout: str
    stderr: str
    truncated: bool
    duration_seconds: float


class CommandRunner:
    def __init__(
        self,
        filesystem: FilesystemPolicy,
        *,
        allowed_executables: frozenset[str],
        allowed_environment: frozenset[str] = frozenset(),
    ) -> None:
        self._filesystem = filesystem
        self._executables = allowed_executables
        self._environment = allowed_environment

    async def run(
        self, command: StructuredCommand, cancellation: asyncio.Event | None = None
    ) -> ProcessResult:
        executable = Path(command.executable).name
        if executable not in self._executables:
            raise SandboxPolicyError("Executable is not allowlisted")
        working = self._filesystem.resolve(command.working_directory)
        environment = {"PATH": os.environ.get("PATH", "")}
        for key, value in command.environment:
            if key not in self._environment or _looks_secret(key):
                raise SandboxPolicyError("Environment variable is not allowlisted")
            environment[key] = value
        if command.network_required:
            raise SandboxPolicyError("Command requires network but no network grant was supplied")
        started = asyncio.get_running_loop().time()
        process = await asyncio.create_subprocess_exec(
            command.executable,
            *command.arguments,
            cwd=working,
            env=environment,
            stdin=asyncio.subprocess.PIPE if command.stdin is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=0x00000200 if sys.platform == "win32" else 0,
            start_new_session=sys.platform != "win32",
        )
        communicate = asyncio.create_task(process.communicate(command.stdin))
        cancel_wait = asyncio.create_task((cancellation or asyncio.Event()).wait())
        try:
            done, _ = await asyncio.wait(
                {communicate, cancel_wait},
                timeout=command.timeout_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if communicate not in done:
                _terminate_process_group(process)
                await process.wait()
                if cancel_wait in done:
                    raise asyncio.CancelledError
                raise TimeoutError("Command execution timed out")
            stdout, stderr = communicate.result()
        finally:
            cancel_wait.cancel()
            if not communicate.done():
                communicate.cancel()
        limit = min(command.output_limit, 10_000_000)
        truncated = len(stdout) > limit or len(stderr) > limit
        return ProcessResult(
            int(process.returncode or 0),
            _redact(stdout[:limit].decode(errors="replace")),
            _redact(stderr[:limit].decode(errors="replace")),
            truncated,
            asyncio.get_running_loop().time() - started,
        )


class FlyMachinesTransport(Protocol):
    async def create(self, configuration: dict[str, object]) -> str: ...
    async def status(self, machine_id: str) -> str: ...
    async def execute(self, machine_id: str, command: StructuredCommand) -> ProcessResult: ...
    async def stop(self, machine_id: str) -> None: ...
    async def destroy(self, machine_id: str) -> None: ...


class FlySandboxAdapter:
    def __init__(self, transport: FlyMachinesTransport, approved_images: frozenset[str]) -> None:
        self._transport = transport
        self._images = approved_images

    async def create(self, image: str, record: SandboxRecord) -> str:
        if image not in self._images:
            raise SandboxPolicyError("Fly sandbox image is not approved")
        return await self._transport.create(
            {
                "image": image,
                "memory_mb": record.resources.memory_mb,
                "cpu": record.resources.cpu_count,
                "network": "deny",
                "task_id": record.task_id,
            }
        )


def docker_command(
    image: str, record: SandboxRecord, command: StructuredCommand
) -> tuple[str, ...]:
    return (
        "docker",
        "run",
        "--rm",
        "--network=none",
        "--read-only",
        "--user=10001:10001",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        f"--cpus={record.resources.cpu_count}",
        f"--memory={record.resources.memory_mb}m",
        f"--pids-limit={record.resources.pid_limit}",
        "--mount",
        f"type=bind,src={record.workspace},dst=/workspace",
        "--workdir=/workspace",
        image,
        command.executable,
        *command.arguments,
    )


def new_sandbox(
    sandbox_id: str, task_id: str, repository_id: str, base_sha: str, workspace: Path
) -> SandboxRecord:
    now = datetime.now(UTC)
    return SandboxRecord(
        sandbox_id,
        task_id,
        repository_id,
        base_sha,
        workspace,
        workspace / ".mezo-evidence",
        ResourcePolicy(),
        now,
        now + timedelta(hours=1),
    )


def _terminate_process_group(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    if sys.platform == "win32":
        process.terminate()
    else:
        os.killpg(process.pid, signal.SIGTERM)


def _looks_secret(key: str) -> bool:
    return bool(re.search(r"(TOKEN|SECRET|PASSWORD|PRIVATE_KEY|CREDENTIAL)", key, re.I))


def _redact(value: str) -> str:
    return re.sub(r"(?i)(token|secret|password)=\S+", r"\1=[REDACTED]", value)
