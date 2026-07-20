from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field


class SkillIntegrityError(RuntimeError):
    pass


class SkillFile(BaseModel):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SkillManifestEntry(BaseModel):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,63}$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    files: tuple[SkillFile, ...]


class SkillManifest(BaseModel):
    repository: str
    commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    skills: tuple[SkillManifestEntry, ...]

    def canonical_hash(self) -> str:
        return hashlib.sha256(
            json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


@dataclass(frozen=True)
class LoadedSkill:
    name: str
    version: str
    content: str
    references: tuple[tuple[str, str], ...]
    commit_sha: str
    manifest_hash: str


class SkillLoader:
    def __init__(
        self,
        root: Path,
        manifest: SkillManifest,
        *,
        approved_repository: str,
        approved_commit: str,
    ) -> None:
        self.root = root.resolve()
        self.manifest = manifest
        if manifest.repository != approved_repository or manifest.commit_sha != approved_commit:
            raise SkillIntegrityError("Skill repository identity or commit is not approved")

    def load(self, name: str) -> LoadedSkill:
        entry = next((item for item in self.manifest.skills if item.name == name), None)
        if entry is None:
            raise SkillIntegrityError(f"Required skill is unknown: {name}")
        content: str | None = None
        references: list[tuple[str, str]] = []
        for file in entry.files:
            path = self._resolve(file.path)
            if path.name != "SKILL.md" and "references" not in path.parts:
                raise SkillIntegrityError("Manifest contains an unapproved skill file")
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != file.sha256:
                raise SkillIntegrityError(f"Skill file hash mismatch: {file.path}")
            text = raw.decode("utf-8").replace("\r\n", "\n")
            if path.name == "SKILL.md":
                content = text
                self._validate_frontmatter(text, entry)
                self._detect_injection(text)
            else:
                references.append((file.path, text))
                self._detect_injection(text)
        if content is None:
            raise SkillIntegrityError("Skill manifest does not include SKILL.md")
        self._validate_reference_links(content, {file.path for file in entry.files})
        return LoadedSkill(
            entry.name,
            entry.version,
            content,
            tuple(sorted(references)),
            self.manifest.commit_sha,
            self.manifest.canonical_hash(),
        )

    def load_required(self, names: tuple[str, ...]) -> tuple[LoadedSkill, ...]:
        return tuple(self.load(name) for name in names)

    def _resolve(self, value: str) -> Path:
        pure = PurePosixPath(value)
        if pure.is_absolute() or ".." in pure.parts:
            raise SkillIntegrityError("Skill reference path escapes repository")
        path = (self.root / Path(*pure.parts)).resolve()
        if not path.is_relative_to(self.root):
            raise SkillIntegrityError("Skill reference path escapes repository")
        return path

    @staticmethod
    def _validate_frontmatter(text: str, entry: SkillManifestEntry) -> None:
        if not text.startswith("---\n") or "\n---\n" not in text[4:]:
            raise SkillIntegrityError("Skill frontmatter is missing")
        raw = text.split("---\n", 2)[1]
        metadata = yaml.safe_load(raw)
        if not isinstance(metadata, dict):
            raise SkillIntegrityError("Skill frontmatter is invalid")
        if metadata.get("name") != entry.name or str(metadata.get("version")) != entry.version:
            raise SkillIntegrityError("Skill frontmatter identity does not match manifest")

    @staticmethod
    def _detect_injection(text: str) -> None:
        patterns = (
            r"ignore (all|any|the) previous instructions",
            r"reveal (the )?(system prompt|secret|token)",
            r"send .*credentials",
            r"disable .*security",
            r"execute .*without approval",
        )
        if any(re.search(pattern, text, re.I) for pattern in patterns):
            raise SkillIntegrityError("Potential prompt injection in skill content")

    @staticmethod
    def _validate_reference_links(content: str, allowed: set[str]) -> None:
        for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", content):
            if target.startswith(("https://", "http://", "#")):
                continue
            if ".." in PurePosixPath(target).parts:
                raise SkillIntegrityError("Skill reference link escapes its package")
            if not any(path.endswith(target) for path in allowed):
                raise SkillIntegrityError(f"Unmanifested skill reference: {target}")


class GuardFinding(BaseModel):
    severity: str = Field(pattern=r"^(critical|important|advisory)$")
    path: str
    evidence: str
    correction: str


class RuntimeGuardReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str
    attempt_id: str
    skill_name: str
    version: str
    commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewed_base: str = Field(pattern=r"^[0-9a-f]{40}$")
    reviewed_head: str = Field(pattern=r"^[0-9a-f]{40}$")
    reviewed_files: tuple[str, ...]
    findings: tuple[GuardFinding, ...]
    evidence: tuple[str, ...]
    corrections: tuple[str, ...]
    remaining_exceptions: tuple[str, ...]
    revisit_condition: str
    started_at: datetime
    completed_at: datetime
    provider: str
    model: str
    receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


def receipt_hash(values: dict[str, Any]) -> str:
    canonical = {key: value for key, value in values.items() if key != "receipt_hash"}
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


class SkillCache:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], LoadedSkill] = {}

    def get(self, commit: str, manifest_hash: str) -> LoadedSkill | None:
        return self._items.get((commit, manifest_hash))

    def put(self, skill: LoadedSkill) -> None:
        self._items[(skill.commit_sha, skill.manifest_hash)] = skill


def now_utc() -> datetime:
    return datetime.now(UTC)
