"""add issue round-trip fields

Revision ID: 0003_add_issue_roundtrip_fields
Revises: 0002_create_documents_issues
Create Date: 2026-08-16 00:30:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "0003_add_issue_roundtrip_fields"
down_revision = "0002_create_documents_issues"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "issues",
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "issues",
        sa.Column("page", sa.Integer(), nullable=True),
    )
    op.add_column(
        "issues",
        sa.Column("issue_type", sa.String(length=64), nullable=True),
    )

    op.execute(
        sa.text(
            """
            UPDATE issues
            SET
                document_id = documents.document_id,
                page = document_blocks.page,
                issue_type = 'literal'
            FROM documents, document_blocks
            WHERE issues.job_id = documents.job_id
              AND issues.job_id = document_blocks.job_id
              AND issues.block_id = document_blocks.block_id
            """
        )
    )

    op.alter_column("issues", "document_id", nullable=False)
    op.alter_column("issues", "issue_type", nullable=False)


def downgrade() -> None:
    op.drop_column("issues", "issue_type")
    op.drop_column("issues", "page")
    op.drop_column("issues", "document_id")
