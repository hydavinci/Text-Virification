"""finalize verification pipeline persistence and recovery

Revision ID: 0004_finalize_verification_pipeline
Revises: 0003_add_job_leases
Create Date: 2026-09-01 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "0004_finalize_verification_pipeline"
down_revision = "0003_add_job_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("rescue_due_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column(
            "rescue_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "jobs",
        sa.Column(
            "rescue_last_published_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.execute(
        "UPDATE jobs "
        "SET rescue_due_at = COALESCE("
        "lease_expires_at, updated_at + INTERVAL '2 minutes'"
        ")"
    )
    op.alter_column("jobs", "rescue_due_at", nullable=False)
    op.create_check_constraint(
        "ck_jobs_rescue_attempts",
        "jobs",
        "rescue_attempts >= 0",
    )
    op.create_index(
        "ix_jobs_rescue_due_at",
        "jobs",
        ["rescue_due_at"],
        unique=False,
    )
    op.add_column(
        "documents",
        sa.Column(
            "parser_name",
            sa.Text(),
            nullable=False,
            server_default="legacy-persisted",
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "parser_version",
            sa.Text(),
            nullable=False,
            server_default="1",
        ),
    )
    op.create_table(
        "document_blocks",
        sa.Column("block_row_id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("block_index", sa.Integer(), nullable=False),
        sa.Column("block_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("global_start", sa.Integer(), nullable=False),
        sa.Column("global_end", sa.Integer(), nullable=False),
        sa.Column("block_start", sa.Integer(), nullable=False),
        sa.Column("block_end", sa.Integer(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("paragraph_index", sa.Integer(), nullable=True),
        sa.Column("table_index", sa.Integer(), nullable=True),
        sa.Column("row_index", sa.Integer(), nullable=True),
        sa.Column("cell_index", sa.Integer(), nullable=True),
        sa.Column(
            "bbox",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("parent_id", sa.Text(), nullable=True),
        sa.Column(
            "style",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "source_locator",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.document_id"],
            name="fk_document_blocks_document",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "document_id",
            "block_id",
            name="uq_document_blocks_identity",
        ),
        sa.UniqueConstraint(
            "document_id",
            "block_index",
            name="uq_document_blocks_order",
        ),
        sa.CheckConstraint("block_index >= 0", name="ck_document_blocks_index"),
        sa.CheckConstraint(
            "global_start >= 0 AND global_end >= global_start",
            name="ck_document_blocks_global_range",
        ),
        sa.CheckConstraint(
            "block_start >= 0 AND block_end >= block_start",
            name="ck_document_blocks_local_range",
        ),
    )
    op.execute(
        "INSERT INTO document_blocks ("
        "document_id, block_index, block_id, kind, text, "
        "global_start, global_end, block_start, block_end, "
        "page, paragraph_index, table_index, row_index, cell_index, "
        "bbox, parent_id, style, source_locator"
        ") "
        "SELECT document_id, 0, 'file-0', 'paragraph', text, "
        "0, char_length(text), 0, char_length(text), "
        "NULL, NULL, NULL, NULL, NULL, NULL, NULL, "
        "'{}'::jsonb, "
        "'{\"locator_kind\":\"file\",\"note\":\"migrated persisted result\"}'::jsonb "
        "FROM documents"
    )
    op.execute(
        'UPDATE verification_issues SET '
        "block_id = 'file-0', "
        "block_start = start, "
        'block_end = "end" '
        "WHERE block_id IS NOT NULL "
        "OR block_start IS NOT NULL "
        "OR block_end IS NOT NULL"
    )
    op.create_foreign_key(
        "fk_verification_issues_document_block",
        "verification_issues",
        "document_blocks",
        ["document_id", "block_id"],
        ["document_id", "block_id"],
        ondelete="CASCADE",
    )
    op.alter_column("documents", "parser_name", server_default=None)
    op.alter_column("documents", "parser_version", server_default=None)


def downgrade() -> None:
    op.drop_constraint(
        "fk_verification_issues_document_block",
        "verification_issues",
        type_="foreignkey",
    )
    op.drop_table("document_blocks")
    op.drop_column("documents", "parser_version")
    op.drop_column("documents", "parser_name")
    op.drop_index("ix_jobs_rescue_due_at", table_name="jobs")
    op.drop_constraint("ck_jobs_rescue_attempts", "jobs", type_="check")
    op.drop_column("jobs", "rescue_last_published_at")
    op.drop_column("jobs", "rescue_attempts")
    op.drop_column("jobs", "rescue_due_at")
