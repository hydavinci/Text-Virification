"""create document analysis tables

Revision ID: 0002_create_documents_issues
Revises: 0001_create_jobs_and_events
Create Date: 2026-08-16 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "0002_create_documents_issues"
down_revision = "0001_create_jobs_and_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("file_type", sa.String(length=16), nullable=False),
        sa.Column("source_name", sa.String(length=255), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.job_id"], ondelete="CASCADE"),
    )

    op.create_table(
        "document_blocks",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("block_id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("block_order", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("paragraph_index", sa.Integer(), nullable=True),
        sa.Column("parent_id", sa.String(length=64), nullable=True),
        sa.Column("style_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "source_locator_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["job_id"], ["documents.job_id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_document_blocks_job_order",
        "document_blocks",
        ["job_id", "block_order"],
        unique=True,
    )

    op.create_table(
        "issues",
        sa.Column("issue_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_version", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("rule_id", sa.String(length=128), nullable=False),
        sa.Column("block_id", sa.String(length=64), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("original", sa.Text(), nullable=False),
        sa.Column("suggestion", sa.Text(), nullable=True),
        sa.Column("alternatives_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_version", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("auto_fixable", sa.Boolean(), nullable=False),
        sa.Column("context", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["documents.job_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["job_id", "block_id"],
            ["document_blocks.job_id", "document_blocks.block_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_issues_job_category", "issues", ["job_id", "category"], unique=False)
    op.create_index("ix_issues_job_severity", "issues", ["job_id", "severity"], unique=False)
    op.create_index(
        "ix_issues_job_block_start",
        "issues",
        ["job_id", "block_id", "start_offset"],
        unique=False,
    )

    op.create_table(
        "checker_failures",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("category", sa.String(length=32), primary_key=True, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["documents.job_id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("checker_failures")
    op.drop_index("ix_issues_job_block_start", table_name="issues")
    op.drop_index("ix_issues_job_severity", table_name="issues")
    op.drop_index("ix_issues_job_category", table_name="issues")
    op.drop_table("issues")
    op.drop_index("ix_document_blocks_job_order", table_name="document_blocks")
    op.drop_table("document_blocks")
    op.drop_table("documents")
