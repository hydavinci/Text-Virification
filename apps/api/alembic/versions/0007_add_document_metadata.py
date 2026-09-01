"""persist typed document metadata

Revision ID: 0007_add_document_metadata
Revises: 0006_add_artifact_lifecycle
Create Date: 2026-09-01 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0007_add_document_metadata"
down_revision = "0006_add_artifact_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.alter_column("documents", "metadata", server_default=None)


def downgrade() -> None:
    op.drop_column("documents", "metadata")
