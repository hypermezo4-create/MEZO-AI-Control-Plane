"""Add the append-only hash-chained evidence ledger.

Revision ID: 0003_evidence_ledger
Revises: 0002_workflow_delivery_records
Create Date: 2026-07-20
"""

from collections.abc import Sequence

from alembic import op
from mezo_control_plane.database import control_records  # noqa: F401
from mezo_control_plane.database.base import Base

revision: str = "0003_evidence_ledger"
down_revision: str | None = "0002_workflow_delivery_records"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    Base.metadata.tables["evidence_ledger"].create(bind=op.get_bind())


def downgrade() -> None:
    op.drop_table("evidence_ledger")
