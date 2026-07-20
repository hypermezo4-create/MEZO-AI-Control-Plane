from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceCitation:
    repository: str
    commit_sha: str
    path: str
    start_line: int
    end_line: int
    symbol: str | None
    analyzer_version: str
    content_hash: str


@dataclass(frozen=True)
class ContextItem:
    citation: SourceCitation
    content: str
    reason: str
    score: float
    estimated_tokens: int


@dataclass(frozen=True)
class RuleDocument:
    path: str
    scope: str
    content: str
    content_hash: str


@dataclass(frozen=True)
class RuleConflict:
    scope: str
    paths: tuple[str, ...]
    statement: str


@dataclass(frozen=True)
class Symbol:
    name: str
    kind: str
    path: str
    line: int
    imports: tuple[str, ...] = ()


@dataclass(frozen=True)
class RepositoryMap:
    files: tuple[str, ...]
    languages: tuple[tuple[str, int], ...]
    tests: tuple[str, ...]
    docs: tuple[str, ...]
    workflows: tuple[str, ...]
    deployment_files: tuple[str, ...]
    generated: tuple[str, ...]
    vendor: tuple[str, ...]
    sensitive: tuple[str, ...]

