"""index queued exports for recovery

Revision ID: 0009_index_queued_exports
Revises: 0008_create_exports
Create Date: 2026-08-17 18:55:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0009_index_queued_exports"
down_revision = "0008_create_exports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_exports_queued_created_at",
        "exports",
        ["created_at", "export_id"],
        unique=False,
        postgresql_where=sa.text("status = 'queued'"),
    )


def downgrade() -> None:
    op.drop_index("ix_exports_queued_created_at", table_name="exports")
