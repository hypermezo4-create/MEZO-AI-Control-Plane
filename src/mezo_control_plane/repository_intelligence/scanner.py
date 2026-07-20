from __future__ import annotations

import ast
import hashlib
import re
from collections import Counter
from pathlib import Path, PurePosixPath

from mezo_control_plane.repository_intelligence.contracts import (
    RepositoryMap,
    RuleConflict,
    RuleDocument,
    Symbol,
)

ANALYZER_VERSION = "1.0.0"
SENSITIVE_PATTERNS = (
    re.compile(r"(^|/)(\.env($|\.)|id_rsa|id_ed25519|.*\.pem$|.*\.key$)", re.I),
    re.compile(r"(^|/)(secrets?|credentials?)(/|\.|$)", re.I),
)
EXCLUDED_DIRS = frozenset({".git", "node_modules", "vendor", ".venv", "dist", "build"})


def is_sensitive(path: str) -> bool:
    normalized = str(PurePosixPath(path))
    return any(pattern.search(normalized) for pattern in SENSITIVE_PATTERNS)


class RepositoryScanner:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def files(self) -> tuple[Path, ...]:
        result: list[Path] = []
        for path in self.root.rglob("*"):
            relative = path.relative_to(self.root)
            if any(part in EXCLUDED_DIRS for part in relative.parts):
                continue
            if path.is_symlink():
                if not path.resolve().is_relative_to(self.root):
                    raise ValueError(f"Symlink escapes repository: {relative.as_posix()}")
                continue
            if path.is_file():
                result.append(path)
        return tuple(sorted(result, key=lambda item: item.relative_to(self.root).as_posix()))

    def map(self) -> RepositoryMap:
        files = tuple(path.relative_to(self.root).as_posix() for path in self.files())
        languages = Counter(_language(path) for path in files)
        languages.pop("unknown", None)
        return RepositoryMap(
            files=files,
            languages=tuple(sorted(languages.items())),
            tests=tuple(path for path in files if _is_test(path)),
            docs=tuple(path for path in files if path.lower().endswith((".md", ".rst"))),
            workflows=tuple(path for path in files if path.startswith(".github/workflows/")),
            deployment_files=tuple(
                path
                for path in files
                if PurePosixPath(path).name in {"Dockerfile", "fly.toml", "docker-compose.yml"}
            ),
            generated=tuple(
                path for path in files if ".generated." in path or path.endswith(".min.js")
            ),
            vendor=tuple(path for path in files if "vendor" in PurePosixPath(path).parts),
            sensitive=tuple(path for path in files if is_sensitive(path)),
        )

    def rules(self) -> tuple[RuleDocument, ...]:
        names = {"AGENTS.md", "README.md", "CONTRIBUTING.md", "SECURITY.md"}
        documents = []
        for path in self.files():
            if path.name not in names:
                continue
            relative = path.relative_to(self.root).as_posix()
            content = path.read_text(encoding="utf-8", errors="replace")
            scope = str(PurePosixPath(relative).parent)
            documents.append(
                RuleDocument(relative, scope if scope != "." else "", content, _hash(content))
            )
        return tuple(documents)

    def applicable_rules(self, target_path: str) -> tuple[RuleDocument, ...]:
        parent = PurePosixPath(target_path).parent
        return tuple(
            rule
            for rule in self.rules()
            if not rule.scope
            or parent == PurePosixPath(rule.scope)
            or PurePosixPath(rule.scope) in parent.parents
        )

    def conflicts(self) -> tuple[RuleConflict, ...]:
        conflicts = []
        by_scope: dict[str, list[RuleDocument]] = {}
        for rule in self.rules():
            by_scope.setdefault(rule.scope, []).append(rule)
        for scope, rules in by_scope.items():
            joined = "\n".join(rule.content.lower() for rule in rules)
            if "must not modify" in joined and "may modify" in joined:
                conflicts.append(
                    RuleConflict(
                        scope,
                        tuple(rule.path for rule in rules),
                        "modify permission conflict",
                    )
                )
        return tuple(conflicts)

    def symbols(self) -> tuple[Symbol, ...]:
        symbols: list[Symbol] = []
        for path in self.files():
            relative = path.relative_to(self.root).as_posix()
            if path.suffix != ".py" or is_sensitive(relative):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            imports = tuple(
                sorted(
                    {
                        alias.name
                        for node in ast.walk(tree)
                        if isinstance(node, ast.Import)
                        for alias in node.names
                    }
                    | {
                        node.module or ""
                        for node in ast.walk(tree)
                        if isinstance(node, ast.ImportFrom)
                    }
                )
            )
            for node in ast.walk(tree):
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.append(
                        Symbol(
                            node.name,
                            type(node).__name__.lower(),
                            relative,
                            node.lineno,
                            imports,
                        )
                    )
        return tuple(sorted(symbols, key=lambda item: (item.path, item.line, item.name)))


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def _is_test(path: str) -> bool:
    name = PurePosixPath(path).name
    return "tests" in PurePosixPath(path).parts or name.startswith("test_")


def _language(path: str) -> str:
    suffix = PurePosixPath(path).suffix.lower()
    return {
        ".py": "python",
        ".sh": "shell",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".json": "json",
        ".java": "java",
        ".kt": "kotlin",
        ".c": "c",
        ".h": "c",
        ".cc": "cpp",
        ".cpp": "cpp",
    }.get(suffix, "unknown")
