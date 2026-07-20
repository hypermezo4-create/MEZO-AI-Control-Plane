from mezo_control_plane.skills.router import SkillRouter


def test_database_concurrency_task_selects_specialized_guards() -> None:
    selection = SkillRouter().select(
        ["src/worker.py", "tests/test_worker.py"],
        "Fix async PostgreSQL queue race and add tests",
    )
    assert "clean-code-guard" in selection.names
    assert "security-guard" in selection.names
    assert "test-guard" in selection.names
    assert "concurrency-guard" in selection.names
    assert "database-guard" in selection.names
