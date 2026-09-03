"""add export artifact reservation ownership version

Revision ID: 0011_add_artifact_reservation_version
Revises: 0010_add_review_revision_chain
Create Date: 2026-09-03 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0011_add_artifact_reservation_version"
down_revision = "0010_add_review_revision_chain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "export_artifacts",
        sa.Column(
            "reservation_version",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_check_constraint(
        "ck_export_artifacts_reservation_version",
        "export_artifacts",
        "reservation_version >= 0",
    )
    op.alter_column(
        "export_artifacts",
        "reservation_version",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_export_artifacts_reservation_version",
        "export_artifacts",
        type_="check",
    )
    op.drop_column("export_artifacts", "reservation_version")
