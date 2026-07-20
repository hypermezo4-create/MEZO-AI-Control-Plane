"""Add durable workflow, agent, delivery, review, skill, and policy records.

Revision ID: 0002_workflow_delivery_records
Revises: 0001_task_evidence_audit
Create Date: 2026-07-20
"""

from collections.abc import Sequence

from alembic import op
from mezo_control_plane.database import control_records  # noqa: F401
from mezo_control_plane.database.base import Base

revision: str = "0002_workflow_delivery_records"
down_revision: str | None = "0001_task_evidence_audit"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

TABLES = (
    "workflow_checkpoints",
    "agent_invocations",
    "prompt_versions",
    "model_attempts",
    "tool_call_records",
    "sandbox_records",
    "repository_analyses",
    "context_citations",
    "github_installation_references",
    "branch_deliveries",
    "review_findings",
    "guard_receipt_records",
    "policy_decision_records",
    "approval_records",
    "draft_pr_deliveries",
)


def upgrade() -> None:
    bind = op.get_bind()
    for name in TABLES:
        Base.metadata.tables[name].create(bind=bind)


def downgrade() -> None:
    for name in reversed(TABLES):
        op.drop_table(name)
