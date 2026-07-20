from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from pathlib import Path


class RepositoryAcquisitionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ClonePolicy:
    allowed_repositories: frozenset[str]
    max_files: int = 100_000
    max_bytes: int = 2_000_000_000
    timeout_seconds: float = 120
    allow_lfs: bool = False
    allow_submodules: bool = False


class RepositoryAcquirer:
    def __init__(self, policy: ClonePolicy) -> None:
        self._policy = policy

    async def acquire(
        self, repository: str, remote_url: str, base_sha: str, destination: Path
    ) -> Path:
        if repository not in self._policy.allowed_repositories:
            raise RepositoryAcquisitionError("Repository is not allowlisted")
        if remote_url not in {
            f"https://github.com/{repository}",
            f"https://github.com/{repository}.git",
        }:
            raise RepositoryAcquisitionError("Remote URL does not match the approved repository")
        if not re.fullmatch(r"[0-9a-f]{40}", base_sha):
            raise RepositoryAcquisitionError("Base commit must be an immutable SHA")
        await asyncio.to_thread(_prepare_destination, destination)
        env = {
            **os.environ,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_LFS_SKIP_SMUDGE": "1",
        }
        commands = (
            ("git", "init", str(destination)),
            (
                "git",
                "-C",
                str(destination),
                "-c",
                "protocol.file.allow=never",
                "-c",
                "core.hooksPath=",
                "fetch",
                "--depth=1",
                "--no-tags",
                remote_url,
                base_sha,
            ),
            (
                "git",
                "-C",
                str(destination),
                "-c",
                "core.hooksPath=",
                "checkout",
                "--detach",
                base_sha,
            ),
        )
        try:
            for command in commands:
                process = await asyncio.create_subprocess_exec(
                    *command,
                    env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=self._policy.timeout_seconds
                )
                if process.returncode:
                    raise RepositoryAcquisitionError(
                        f"Git acquisition failed with exit code {process.returncode}: "
                        f"{stderr.decode(errors='replace')[:500]}"
                    )
        except TimeoutError as error:
            raise RepositoryAcquisitionError("Repository checkout timed out") from error
        self._validate_checkout(destination)
        return destination

    def _validate_checkout(self, root: Path) -> None:
        count = 0
        size = 0
        resolved_root = root.resolve()
        for path in root.rglob("*"):
            if ".git" in path.parts:
                continue
            if path.is_symlink():
                target = path.resolve()
                if not target.is_relative_to(resolved_root):
                    raise RepositoryAcquisitionError("Checkout contains escaping symlink")
            if path.is_file():
                count += 1
                size += path.stat().st_size
            if count > self._policy.max_files or size > self._policy.max_bytes:
                raise RepositoryAcquisitionError("Repository exceeds acquisition limits")


def _prepare_destination(destination: Path) -> None:
    if destination.exists() and any(destination.iterdir()):
        raise RepositoryAcquisitionError("Clone destination is not empty")
    destination.mkdir(parents=True, exist_ok=True)
