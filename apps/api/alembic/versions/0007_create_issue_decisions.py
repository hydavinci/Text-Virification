"""create issue decisions

Revision ID: 0007_create_issue_decisions
Revises: 0006_add_job_event_metadata
Create Date: 2026-08-17 11:45:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "0007_create_issue_decisions"
down_revision = "0006_add_job_event_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "issue_decisions",
        sa.Column(
            "issue_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("issue_version", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("replacement", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            """
            (
                action = 'custom'
                AND replacement IS NOT NULL
                AND replacement ~ '[^[:space:]]'
            )
            OR (
                action IN ('accepted', 'ignored')
                AND replacement IS NULL
            )
            """,
            name="ck_issue_decisions_action_replacement",
        ),
        sa.ForeignKeyConstraint(["issue_id"], ["issues.issue_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.job_id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_issue_decisions_job_action",
        "issue_decisions",
        ["job_id", "action"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_issue_decisions_job_action", table_name="issue_decisions")
    op.drop_table("issue_decisions")
