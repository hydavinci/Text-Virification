"""add export artifact reservation lifecycle

Revision ID: 0006_add_artifact_lifecycle
Revises: 0005_add_artifact_fingerprints
Create Date: 2026-09-01 12:49:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0006_add_artifact_lifecycle"
down_revision = "0005_add_artifact_fingerprints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "export_artifacts",
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="ready",
        ),
    )
    op.add_column(
        "export_artifacts",
        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "export_artifacts",
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE export_artifacts "
        "SET reserved_at = created_at, ready_at = created_at"
    )
    op.alter_column("export_artifacts", "reserved_at", nullable=False)
    op.alter_column("export_artifacts", "status", server_default=None)
    op.create_check_constraint(
        "ck_export_artifacts_status",
        "export_artifacts",
        "status IN ('pending', 'ready')",
    )
    op.create_check_constraint(
        "ck_export_artifacts_ready_state",
        "export_artifacts",
        "(status = 'pending' AND ready_at IS NULL) "
        "OR (status = 'ready' AND ready_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_export_artifacts_pending_digest",
        "export_artifacts",
        "status <> 'pending' OR content_sha256 IS NOT NULL",
    )
    op.create_index(
        "ix_export_artifacts_status_reserved_at",
        "export_artifacts",
        ["status", "reserved_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_export_artifacts_status_reserved_at",
        table_name="export_artifacts",
    )
    op.drop_constraint(
        "ck_export_artifacts_pending_digest",
        "export_artifacts",
        type_="check",
    )
    op.drop_constraint(
        "ck_export_artifacts_ready_state",
        "export_artifacts",
        type_="check",
    )
    op.drop_constraint(
        "ck_export_artifacts_status",
        "export_artifacts",
        type_="check",
    )
    op.drop_column("export_artifacts", "ready_at")
    op.drop_column("export_artifacts", "reserved_at")
    op.drop_column("export_artifacts", "status")
