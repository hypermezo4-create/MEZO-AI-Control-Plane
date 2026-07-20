from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from mezo_control_plane.repository_intelligence.contracts import ContextItem, SourceCitation
from mezo_control_plane.repository_intelligence.scanner import ANALYZER_VERSION, is_sensitive


@dataclass(frozen=True)
class ContextRequest:
    repository: str
    commit_sha: str
    instruction: str
    hypotheses: tuple[str, ...] = ()
    changed_paths: tuple[str, ...] = ()
    max_tokens: int = 12_000
    reserved_tokens: int = 2_000


class ContextBuilder:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def build(self, request: ContextRequest) -> tuple[ContextItem, ...]:
        terms = set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", request.instruction.lower()))
        terms.update(term.lower() for item in request.hypotheses for term in item.split())
        budget = max(0, request.max_tokens - request.reserved_tokens)
        candidates: list[ContextItem] = []
        for path in self.root.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(self.root).as_posix()
            if is_sensitive(relative) or _excluded(relative):
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for start, chunk in _chunks(content):
                lowered = chunk.lower()
                matches = sum(1 for term in terms if term in lowered)
                path_relevance = 3 if relative in request.changed_paths else 0
                test_relevance = 1 if "test" in relative.lower() else 0
                rule_relevance = 4 if PurePosixPath(relative).name == "AGENTS.md" else 0
                score = float(matches + path_relevance + test_relevance + rule_relevance)
                if score == 0:
                    continue
                digest = hashlib.sha256(chunk.encode()).hexdigest()
                tokens = max(1, len(chunk) // 4)
                candidates.append(
                    ContextItem(
                        SourceCitation(
                            request.repository,
                            request.commit_sha,
                            relative,
                            start,
                            start + chunk.count("\n"),
                            None,
                            ANALYZER_VERSION,
                            digest,
                        ),
                        chunk,
                        (
                            f"matched {matches} task terms; path={path_relevance}; "
                            f"rules={rule_relevance}"
                        ),
                        score,
                        tokens,
                    )
                )
        chosen: list[ContextItem] = []
        used = 0
        seen: set[str] = set()
        for item in sorted(
            candidates,
            key=lambda value: (-value.score, value.citation.path, value.citation.start_line),
        ):
            if item.citation.content_hash in seen or used + item.estimated_tokens > budget:
                continue
            chosen.append(item)
            seen.add(item.citation.content_hash)
            used += item.estimated_tokens
        return tuple(chosen)


class ContextCache:
    def __init__(self) -> None:
        self._values: dict[tuple[str, str, str, str], tuple[ContextItem, ...]] = {}

    def get(
        self, repository: str, sha: str, analyzer_version: str, configuration_hash: str
    ) -> tuple[ContextItem, ...] | None:
        return self._values.get((repository, sha, analyzer_version, configuration_hash))

    def put(
        self,
        repository: str,
        sha: str,
        analyzer_version: str,
        configuration_hash: str,
        value: tuple[ContextItem, ...],
    ) -> None:
        self._values[(repository, sha, analyzer_version, configuration_hash)] = value


def map_tests(production_path: str, files: tuple[str, ...]) -> tuple[str, ...]:
    stem = PurePosixPath(production_path).stem
    return tuple(
        path
        for path in files
        if ("tests" in PurePosixPath(path).parts or PurePosixPath(path).name.startswith("test_"))
        and stem in PurePosixPath(path).stem
    )


def _chunks(content: str, lines_per_chunk: int = 80) -> tuple[tuple[int, str], ...]:
    lines = content.splitlines()
    return tuple(
        (index + 1, "\n".join(lines[index : index + lines_per_chunk]))
        for index in range(0, len(lines), lines_per_chunk)
    )


def _excluded(path: str) -> bool:
    parts = PurePosixPath(path).parts
    excluded = {".git", "vendor", "node_modules", "dist", "build", ".venv"}
    return any(part in excluded for part in parts)
