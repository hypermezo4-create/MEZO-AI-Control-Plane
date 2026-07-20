import os

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command


def test_phase_07_12_migration_upgrade_and_downgrade() -> None:
    database_url = os.getenv("DATABASE_TEST_URL")
    if not database_url:
        pytest.skip("DATABASE_TEST_URL is required")
    synchronous_url = database_url.replace("+asyncpg", "+psycopg")
    configuration = Config("alembic.ini")
    configuration.set_main_option("sqlalchemy.url", synchronous_url)
    command.downgrade(configuration, "base")
    command.upgrade(configuration, "head")
    engine = create_engine(synchronous_url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert {
            "workflow_checkpoints",
            "agent_invocations",
            "repository_analyses",
            "github_installation_references",
            "sandbox_records",
            "guard_receipt_records",
            "policy_decision_records",
            "approval_records",
            "draft_pr_deliveries",
        } <= tables
        checkpoint_uniques = {
            item["name"] for item in inspect(engine).get_unique_constraints("workflow_checkpoints")
        }
        assert {"uq_workflow_checkpoint_sequence", "uq_workflow_stage_input"} <= checkpoint_uniques
        approval_uniques = {
            item["name"] for item in inspect(engine).get_unique_constraints("approval_records")
        }
        assert "approval_records_approval_id_key" in approval_uniques
    finally:
        engine.dispose()
    command.downgrade(configuration, "0001_task_evidence_audit")
    engine = create_engine(synchronous_url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert "workflow_checkpoints" not in tables
        assert "tasks" in tables
    finally:
        engine.dispose()
    command.upgrade(configuration, "head")
