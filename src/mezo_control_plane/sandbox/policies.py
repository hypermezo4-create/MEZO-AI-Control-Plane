from __future__ import annotations

import ipaddress
import os
import socket
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class SandboxPolicyError(RuntimeError):
    pass


@dataclass(frozen=True)
class FilesystemPolicy:
    workspace: Path
    protected_paths: frozenset[str] = frozenset({".git", ".github/workflows"})

    def resolve(self, candidate: str, *, write: bool = False, approved: bool = False) -> Path:
        normalized = candidate.replace("\\", "/")
        pure = PurePosixPath(normalized)
        if (
            pure.is_absolute()
            or Path(candidate).is_absolute()
            or (len(normalized) >= 2 and normalized[1] == ":")
            or ".." in pure.parts
        ):
            raise SandboxPolicyError("Path is outside the workspace")
        if normalized in {"", "."}:
            return self.workspace.resolve()
        root = self.workspace.resolve()
        target = (root / Path(*pure.parts)).resolve(strict=False)
        if not target.is_relative_to(root):
            raise SandboxPolicyError("Path escapes through a symlink")
        current = root
        for part in pure.parts:
            current = current / part
            if (
                current.exists()
                and current.is_symlink()
                and not current.resolve().is_relative_to(root)
            ):
                raise SandboxPolicyError("Path escapes through a symlink")
        lowered = normalized.casefold()
        if (
            write
            and not approved
            and any(
                lowered == item.casefold() or lowered.startswith(f"{item.casefold()}/")
                for item in self.protected_paths
            )
        ):
            raise SandboxPolicyError("Protected path requires approval")
        if target.exists() and target.is_file() and os.stat(target).st_nlink > 1:
            raise SandboxPolicyError("Hard-linked files are not permitted")
        return target


@dataclass(frozen=True)
class NetworkPolicy:
    allowed_hosts: frozenset[str] = frozenset()
    allowed_ports: frozenset[int] = frozenset({443})

    def authorize(self, host: str, port: int, resolved_addresses: tuple[str, ...]) -> None:
        if host not in self.allowed_hosts or port not in self.allowed_ports:
            raise SandboxPolicyError("Network destination is not approved")
        for address in resolved_addresses:
            ip = ipaddress.ip_address(address)
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_multicast
                or address == "169.254.169.254"
            ):
                raise SandboxPolicyError("Private or metadata network address denied")

    async def resolve_and_authorize(self, host: str, port: int) -> tuple[str, ...]:
        import asyncio

        loop = asyncio.get_running_loop()
        records = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        addresses = tuple(sorted({str(record[4][0]) for record in records}))
        self.authorize(host, port, addresses)
        return addresses
