import hashlib
from pathlib import Path

import pytest

from mezo_control_plane.repository_intelligence.context_builder import (
    ContextBuilder,
    ContextCache,
    ContextRequest,
    map_tests,
)
from mezo_control_plane.repository_intelligence.scanner import RepositoryScanner


def _write(root: Path, name: str, content: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_nested_agents_scope_and_symbol_test_mapping(tmp_path: Path) -> None:
    _write(tmp_path, "AGENTS.md", "global rules")
    _write(tmp_path, "src/AGENTS.md", "nested rules")
    _write(tmp_path, "src/service.py", "import os\ndef execute_task():\n    return 1\n")
    _write(tmp_path, "tests/test_service.py", "def test_execute_task(): pass")
    scanner = RepositoryScanner(tmp_path)
    rules = scanner.applicable_rules("src/service.py")
    assert [rule.path for rule in rules] == ["AGENTS.md", "src/AGENTS.md"]
    assert any(symbol.name == "execute_task" for symbol in scanner.symbols())
    assert map_tests("src/service.py", scanner.map().files) == ("tests/test_service.py",)


def test_rule_conflict_is_structured(tmp_path: Path) -> None:
    _write(tmp_path, "AGENTS.md", "must not modify generated files; maintainers may modify them")
    assert RepositoryScanner(tmp_path).conflicts()[0].statement == "modify permission conflict"


def test_context_excludes_secrets_deduplicates_and_respects_budget(tmp_path: Path) -> None:
    _write(tmp_path, ".env", "TOKEN=secret")
    _write(tmp_path, "src/a.py", "queue retry recovery\n" * 10)
    _write(tmp_path, "src/b.py", "queue retry recovery\n" * 10)
    request = ContextRequest(
        "owner/repo", "a" * 40, "queue retry", max_tokens=100, reserved_tokens=10
    )
    items = ContextBuilder(tmp_path).build(request)
    assert items
    assert all(item.citation.path != ".env" for item in items)
    assert len({item.citation.content_hash for item in items}) == len(items)
    assert sum(item.estimated_tokens for item in items) <= 90


def test_context_order_is_deterministic_and_citations_pin_sha(tmp_path: Path) -> None:
    _write(tmp_path, "b.py", "target symbol")
    _write(tmp_path, "a.py", "target symbol different")
    request = ContextRequest("owner/repo", "b" * 40, "target symbol")
    first = ContextBuilder(tmp_path).build(request)
    second = ContextBuilder(tmp_path).build(request)
    assert first == second
    assert all(item.citation.commit_sha == "b" * 40 for item in first)


def test_context_cache_key_invalidates_on_sha_or_configuration() -> None:
    cache = ContextCache()
    cache.put("owner/repo", "a" * 40, "1", "cfg", ())
    assert cache.get("owner/repo", "a" * 40, "1", "cfg") == ()
    assert cache.get("owner/repo", "b" * 40, "1", "cfg") is None
    assert cache.get("owner/repo", "a" * 40, "1", hashlib.sha256(b"cfg").hexdigest()) is None


def test_symlink_escape_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-mezo-test"
    outside.write_text("external", encoding="utf-8")
    link = tmp_path / "escape"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Symlink creation is unavailable")
    with pytest.raises(ValueError, match="escapes"):
        RepositoryScanner(tmp_path).files()
