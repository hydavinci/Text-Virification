"""add durable job processing leases

Revision ID: 0003_add_job_leases
Revises: 0002_add_verification_results
Create Date: 2026-09-01 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "0003_add_job_leases"
down_revision = "0002_add_verification_results"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column(
            "lease_owner_token",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "jobs",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_jobs_lease_pair",
        "jobs",
        "(lease_owner_token IS NULL AND lease_expires_at IS NULL) "
        "OR (lease_owner_token IS NOT NULL AND lease_expires_at IS NOT NULL)",
    )
    op.create_index(
        "ix_jobs_lease_expires_at",
        "jobs",
        ["lease_expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_lease_expires_at", table_name="jobs")
    op.drop_constraint("ck_jobs_lease_pair", "jobs", type_="check")
    op.drop_column("jobs", "lease_expires_at")
    op.drop_column("jobs", "lease_owner_token")
