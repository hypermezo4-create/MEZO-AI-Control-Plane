from __future__ import annotations

import asyncio
import hashlib
import os
import re
from pathlib import Path

from mezo_control_plane.sandbox.policies import FilesystemPolicy
from mezo_control_plane.tools.contracts import (
    ApplyPatchInput,
    ListDirectoryInput,
    ReadFileInput,
    SearchCodeInput,
)


class FilesystemTools:
    def __init__(self, policy: FilesystemPolicy) -> None:
        self._policy = policy

    async def read_file(self, value: ReadFileInput) -> dict[str, object]:
        path = self._policy.resolve(value.path)
        data = await asyncio.to_thread(path.read_bytes)
        if len(data) > value.max_bytes:
            raise ValueError("File exceeds read limit")
        if b"\x00" in data:
            raise ValueError("Binary file reads are not permitted")
        return {"path": value.path, "content": data.decode(), "sha256": _hash(data)}

    async def list_directory(self, value: ListDirectoryInput) -> dict[str, object]:
        path = self._policy.resolve(value.path)
        entries = await asyncio.to_thread(lambda: sorted(item.name for item in path.iterdir()))
        if len(entries) > value.limit:
            entries = entries[: value.limit]
        return {"path": value.path, "entries": entries}

    async def search_code(self, value: SearchCodeInput) -> dict[str, object]:
        root = self._policy.resolve(value.path)

        def search() -> list[dict[str, object]]:
            results = []
            pattern = re.compile(re.escape(value.query), re.I)
            for path in sorted(root.rglob("*")):
                if not path.is_file() or path.is_symlink():
                    continue
                try:
                    lines = path.read_text(encoding="utf-8").splitlines()
                except (UnicodeDecodeError, OSError):
                    continue
                for number, line in enumerate(lines, 1):
                    if pattern.search(line):
                        results.append(
                            {
                                "path": path.relative_to(self._policy.workspace).as_posix(),
                                "line": number,
                                "text": line[:500],
                            }
                        )
                        if len(results) >= value.limit:
                            return results
            return results

        return {"matches": await asyncio.to_thread(search)}

    async def apply_patch(self, value: ApplyPatchInput) -> dict[str, object]:
        total = sum(len((item.content or "").encode()) for item in value.files)
        if total > 5_000_000:
            raise ValueError("Patch exceeds byte limit")
        resolved = [
            (
                item,
                self._policy.resolve(
                    item.path, write=True, approved=value.approved_protected_write
                ),
            )
            for item in value.files
        ]
        originals: dict[Path, bytes | None] = {}
        for item, path in resolved:
            original = await asyncio.to_thread(path.read_bytes) if path.exists() else None
            originals[path] = original
            if item.base_hash is not None and _hash(original or b"") != item.base_hash:
                raise ValueError(f"Patch context mismatch: {item.path}")
            if item.content is not None and "\x00" in item.content:
                raise ValueError("Binary patches are not permitted")
        changed: list[str] = []
        try:
            for item, path in resolved:
                if item.delete:
                    if path.exists():
                        await asyncio.to_thread(path.unlink)
                else:
                    if item.content is None:
                        raise ValueError("Non-delete patch requires content")
                    await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
                    temporary = path.with_name(f".{path.name}.mezo-tmp")
                    await asyncio.to_thread(temporary.write_text, item.content, encoding="utf-8")
                    await asyncio.to_thread(os.replace, temporary, path)
                changed.append(item.path)
        except BaseException:
            for path, original in originals.items():
                if original is None:
                    if path.exists():
                        await asyncio.to_thread(path.unlink)
                else:
                    await asyncio.to_thread(path.write_bytes, original)
            raise
        return {"changed_paths": changed, "changed_bytes": total}


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
