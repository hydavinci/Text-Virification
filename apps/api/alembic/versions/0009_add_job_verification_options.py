"""persist asynchronous verification options

Revision ID: 0009_add_job_verification_options
Revises: 0008_add_job_error_identity
Create Date: 2026-09-02 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0009_add_job_verification_options"
down_revision = "0008_add_job_error_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column(
            "verification_options",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("jobs", "verification_options")
