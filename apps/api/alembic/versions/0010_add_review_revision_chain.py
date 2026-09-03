"""add review revision parent chain

Revision ID: 0010_add_review_revision_chain
Revises: 0009_add_job_verification_options
Create Date: 2026-09-03 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0010_add_review_revision_chain"
down_revision = "0009_add_job_verification_options"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "review_revisions",
        sa.Column(
            "parent_revision_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "review_revisions",
        sa.Column(
            "kind",
            sa.String(length=16),
            nullable=False,
            server_default="review",
        ),
    )
    op.create_foreign_key(
        "fk_review_revisions_parent_run",
        "review_revisions",
        "review_revisions",
        ["parent_revision_id", "verification_run_id"],
        ["review_revision_id", "verification_run_id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_review_revisions_kind",
        "review_revisions",
        "kind IN ('review', 'manual')",
    )
    op.alter_column("review_revisions", "kind", server_default=None)


def downgrade() -> None:
    op.drop_constraint(
        "ck_review_revisions_kind",
        "review_revisions",
        type_="check",
    )
    op.drop_constraint(
        "fk_review_revisions_parent_run",
        "review_revisions",
        type_="foreignkey",
    )
    op.drop_column("review_revisions", "kind")
    op.drop_column("review_revisions", "parent_revision_id")
