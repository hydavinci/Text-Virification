"""add job check options

Revision ID: 0004_add_job_check_options
Revises: 0003_add_issue_roundtrip_fields
Create Date: 2026-08-16 23:55:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "0004_add_job_check_options"
down_revision = "0003_add_issue_roundtrip_fields"
branch_labels = None
depends_on = None

DEFAULT_ENABLED_CATEGORIES = (
    '["character","vocabulary","sentence","format","discourse","security"]'
)


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column(
            "scenario",
            sa.String(length=32),
            nullable=False,
            server_default="general",
        ),
    )
    op.add_column(
        "jobs",
        sa.Column(
            "enabled_categories",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_ENABLED_CATEGORIES}'::jsonb"),
        ),
    )
    op.alter_column("jobs", "scenario", server_default=None)
    op.alter_column("jobs", "enabled_categories", server_default=None)


def downgrade() -> None:
    op.drop_column("jobs", "enabled_categories")
    op.drop_column("jobs", "scenario")
