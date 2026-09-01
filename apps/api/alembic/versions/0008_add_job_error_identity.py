"""persist structured job error identity

Revision ID: 0008_add_job_error_identity
Revises: 0007_add_document_metadata
Create Date: 2026-09-01 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0008_add_job_error_identity"
down_revision = "0007_add_document_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("error_stage", sa.String(length=32), nullable=True))
    op.add_column("jobs", sa.Column("error_retryable", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "error_retryable")
    op.drop_column("jobs", "error_stage")
