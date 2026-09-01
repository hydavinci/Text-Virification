"""add export artifact content fingerprints

Revision ID: 0005_add_artifact_fingerprints
Revises: 0004_finalize_verification_pipeline
Create Date: 2026-09-01 12:00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0005_add_artifact_fingerprints"
down_revision = "0004_finalize_verification_pipeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "export_artifacts",
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
    )
    op.create_check_constraint(
        "ck_export_artifacts_sha256",
        "export_artifacts",
        "content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-f]{64}$'",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_export_artifacts_sha256",
        "export_artifacts",
        type_="check",
    )
    op.drop_column("export_artifacts", "content_sha256")
