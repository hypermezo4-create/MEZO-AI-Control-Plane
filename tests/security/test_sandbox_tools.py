import asyncio
import hashlib
import sys
from pathlib import Path

import pytest

from mezo_control_plane.sandbox.manager import CommandRunner, StructuredCommand
from mezo_control_plane.sandbox.policies import (
    FilesystemPolicy,
    NetworkPolicy,
    SandboxPolicyError,
)
from mezo_control_plane.tools.contracts import ApplyPatchInput, StructuredPatchFile
from mezo_control_plane.tools.filesystem import FilesystemTools


def test_path_traversal_absolute_and_protected_paths(tmp_path: Path) -> None:
    policy = FilesystemPolicy(tmp_path)
    for candidate in ("../secret", str(tmp_path.parent / "secret")):
        with pytest.raises(SandboxPolicyError):
            policy.resolve(candidate)
    with pytest.raises(SandboxPolicyError, match="Protected"):
        policy.resolve(".github/workflows/ci.yml", write=True)


def test_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "sandbox-outside"
    outside.mkdir(exist_ok=True)
    link = tmp_path / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks are unavailable")
    with pytest.raises(SandboxPolicyError, match="symlink"):
        FilesystemPolicy(tmp_path).resolve("escape/file")


def test_network_denies_metadata_private_and_unapproved() -> None:
    policy = NetworkPolicy(frozenset({"api.example.com"}), frozenset({443}))
    with pytest.raises(SandboxPolicyError):
        policy.authorize("169.254.169.254", 80, ("169.254.169.254",))
    with pytest.raises(SandboxPolicyError):
        policy.authorize("api.example.com", 443, ("127.0.0.1",))
    with pytest.raises(SandboxPolicyError):
        policy.authorize("evil.example", 443, ("8.8.8.8",))


@pytest.mark.asyncio
async def test_command_runner_has_no_shell_injection_and_redacts(tmp_path: Path) -> None:
    runner = CommandRunner(
        FilesystemPolicy(tmp_path), allowed_executables=frozenset({Path(sys.executable).name})
    )
    result = await runner.run(
        StructuredCommand(
            sys.executable,
            ("-c", "import sys; print(sys.argv[1])", "; echo injected"),
            output_limit=1000,
        )
    )
    assert result.stdout.strip() == "; echo injected"


@pytest.mark.asyncio
async def test_command_timeout_cancellation_and_output_limit(tmp_path: Path) -> None:
    runner = CommandRunner(
        FilesystemPolicy(tmp_path), allowed_executables=frozenset({Path(sys.executable).name})
    )
    with pytest.raises(TimeoutError):
        await runner.run(
            StructuredCommand(
                sys.executable, ("-c", "import time; time.sleep(10)"), timeout_seconds=0.05
            )
        )
    result = await runner.run(
        StructuredCommand(sys.executable, ("-c", "print('x'*1000)"), output_limit=20)
    )
    assert result.truncated and len(result.stdout) == 20
    cancelled = asyncio.Event()
    cancelled.set()
    with pytest.raises(asyncio.CancelledError):
        await runner.run(
            StructuredCommand(sys.executable, ("-c", "import time; time.sleep(10)")), cancelled
        )


@pytest.mark.asyncio
async def test_patch_is_transactional_and_context_checked(tmp_path: Path) -> None:
    target = tmp_path / "a.py"
    target.write_text("old", encoding="utf-8")
    tools = FilesystemTools(FilesystemPolicy(tmp_path))
    with pytest.raises(ValueError, match="context mismatch"):
        await tools.apply_patch(
            ApplyPatchInput(
                files=(StructuredPatchFile(path="a.py", base_hash="0" * 64, content="new"),)
            )
        )
    assert target.read_text(encoding="utf-8") == "old"
    result = await tools.apply_patch(
        ApplyPatchInput(
            files=(
                StructuredPatchFile(
                    path="a.py",
                    base_hash=hashlib.sha256(b"old").hexdigest(),
                    content="new",
                ),
            )
        )
    )
    assert result["changed_paths"] == ["a.py"]
    assert target.read_text(encoding="utf-8") == "new"


@pytest.mark.asyncio
async def test_binary_patch_and_secret_environment_are_denied(tmp_path: Path) -> None:
    tools = FilesystemTools(FilesystemPolicy(tmp_path))
    with pytest.raises(ValueError, match="Binary"):
        await tools.apply_patch(
            ApplyPatchInput(files=(StructuredPatchFile(path="x", content="bad\x00data"),))
        )
    runner = CommandRunner(
        FilesystemPolicy(tmp_path),
        allowed_executables=frozenset({Path(sys.executable).name}),
        allowed_environment=frozenset({"API_TOKEN"}),
    )
    with pytest.raises(SandboxPolicyError, match="Environment"):
        await runner.run(
            StructuredCommand(sys.executable, ("-c", "pass"), environment=(("API_TOKEN", "x"),))
        )
