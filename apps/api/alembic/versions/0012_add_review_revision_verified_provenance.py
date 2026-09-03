"""add verified review revision provenance

Revision ID: 0012_add_revision_provenance
Revises: 0011_add_artifact_reservation_version
Create Date: 2026-09-03 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0012_add_revision_provenance"
down_revision = "0011_add_artifact_reservation_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "review_revisions",
        sa.Column(
            "verified_provenance",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_review_revisions_verified_provenance_object",
        "review_revisions",
        "verified_provenance IS NULL "
        "OR jsonb_typeof(verified_provenance) = 'object'",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_review_revisions_verified_provenance_object",
        "review_revisions",
        type_="check",
    )
    op.drop_column("review_revisions", "verified_provenance")
