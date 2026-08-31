"""add normalized verification result tables

Revision ID: 0002_add_verification_results
Revises: 0001_create_jobs_and_events
Create Date: 2026-08-31 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "0002_add_verification_results"
down_revision = "0001_create_jobs_and_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_version", sa.String(length=255), nullable=False),
        sa.Column("source_name", sa.String(length=255), nullable=False),
        sa.Column("file_type", sa.String(length=16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.job_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("job_id", name="uq_documents_job"),
        sa.UniqueConstraint(
            "document_id",
            "source_version",
            name="uq_documents_identity",
        ),
    )

    op.create_table(
        "verification_runs",
        sa.Column(
            "verification_run_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scenario", sa.String(length=32), nullable=False),
        sa.Column("execution_mode", sa.String(length=32), nullable=False),
        sa.Column("analysis_mode", sa.String(length=32), nullable=False),
        sa.Column("stats_char_count", sa.Integer(), nullable=False),
        sa.Column("stats_char_count_no_space", sa.Integer(), nullable=False),
        sa.Column("stats_line_count", sa.Integer(), nullable=False),
        sa.Column("stats_paragraph_count", sa.Integer(), nullable=False),
        sa.Column("stats_language", sa.String(length=8), nullable=False),
        sa.Column("stats_primary_count", sa.Integer(), nullable=False),
        sa.Column("stats_primary_label", sa.String(length=64), nullable=False),
        sa.Column("summary_total", sa.Integer(), nullable=False),
        sa.Column("summary_by_type", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "summary_by_severity",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("summary_by_rule", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("summary_by_layer", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "summary_llm_review",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "dictionary_versions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("degradation_is_degraded", sa.Boolean(), nullable=False),
        sa.Column(
            "degradation_reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.document_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.job_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("job_id", name="uq_verification_runs_job"),
        sa.CheckConstraint("stats_char_count >= 0", name="ck_runs_stats_char_count"),
        sa.CheckConstraint(
            "stats_char_count_no_space >= 0",
            name="ck_runs_stats_char_count_no_space",
        ),
        sa.CheckConstraint("stats_line_count >= 0", name="ck_runs_stats_line_count"),
        sa.CheckConstraint(
            "stats_paragraph_count >= 0",
            name="ck_runs_stats_paragraph_count",
        ),
        sa.CheckConstraint("stats_primary_count >= 0", name="ck_runs_stats_primary_count"),
        sa.CheckConstraint("summary_total >= 0", name="ck_runs_summary_total"),
    )

    op.create_table(
        "verification_issues",
        sa.Column("issue_row_id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("verification_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("issue_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("issue_index", sa.Integer(), nullable=False),
        sa.Column("block_id", sa.String(length=255), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("start", sa.Integer(), nullable=False),
        sa.Column("end", sa.Integer(), nullable=False),
        sa.Column("block_start", sa.Integer(), nullable=True),
        sa.Column("block_end", sa.Integer(), nullable=True),
        sa.Column("original", sa.Text(), nullable=False),
        sa.Column("suggestion", sa.Text(), nullable=True),
        sa.Column(
            "alternatives",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("layer", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("rule_id", sa.String(length=255), nullable=False),
        sa.Column("rule_version", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=255), nullable=False),
        sa.Column("source_version", sa.String(length=255), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("auto_fixable", sa.Boolean(), nullable=False),
        sa.Column("context", sa.Text(), nullable=False),
        sa.Column("review", sa.String(length=64), nullable=True),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.document_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["verification_run_id"],
            ["verification_runs.verification_run_id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "verification_run_id",
            "issue_id",
            name="uq_verification_issues_run_issue",
        ),
        sa.UniqueConstraint(
            "verification_run_id",
            "issue_index",
            name="uq_verification_issues_run_index",
        ),
        sa.CheckConstraint("issue_index >= 0", name="ck_issues_issue_index"),
        sa.CheckConstraint("start >= 0", name="ck_issues_start"),
        sa.CheckConstraint('"end" > start', name="ck_issues_range"),
        sa.CheckConstraint(
            "(block_start IS NULL AND block_end IS NULL) "
            "OR (block_start >= 0 AND block_end > block_start)",
            name="ck_issues_block_range",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_issues_confidence",
        ),
    )

    op.create_table(
        "review_revisions",
        sa.Column(
            "review_revision_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("verification_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_version", sa.String(length=255), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.document_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["verification_run_id"],
            ["verification_runs.verification_run_id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "verification_run_id",
            "revision_number",
            name="uq_review_revisions_run_number",
        ),
        sa.CheckConstraint("revision_number > 0", name="ck_review_revisions_number"),
    )

    op.create_table(
        "export_artifacts",
        sa.Column(
            "export_artifact_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("verification_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("review_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_version", sa.String(length=255), nullable=False),
        sa.Column("file_type", sa.String(length=16), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["review_revision_id"],
            ["review_revisions.review_revision_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["verification_run_id"],
            ["verification_runs.verification_run_id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("storage_key", name="uq_export_artifacts_storage_key"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_export_artifacts_size"),
    )


def downgrade() -> None:
    op.drop_table("export_artifacts")
    op.drop_table("review_revisions")
    op.drop_table("verification_issues")
    op.drop_table("verification_runs")
    op.drop_table("documents")
