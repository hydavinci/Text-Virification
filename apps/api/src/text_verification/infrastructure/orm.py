from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class JobRow(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "(lease_owner_token IS NULL AND lease_expires_at IS NULL) "
            "OR (lease_owner_token IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_jobs_lease_pair",
        ),
        CheckConstraint(
            "rescue_attempts >= 0",
            name="ck_jobs_rescue_attempts",
        ),
    )

    job_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    source_name: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(16))
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_retryable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    verification_options: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=sql_text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    lease_owner_token: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=True,
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    rescue_due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    rescue_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rescue_last_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    events: Mapped[list[JobEventRow]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="JobEventRow.sequence",
        passive_deletes=True,
    )


class JobEventRow(Base):
    __tablename__ = "job_events"
    __table_args__ = (Index("ix_job_events_job_sequence", "job_id", "sequence", unique=True),)

    event_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("jobs.job_id", ondelete="CASCADE"),
    )
    sequence: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32))
    progress: Mapped[int] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    job: Mapped[JobRow] = relationship(back_populates="events")


class DocumentRow(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("job_id", name="uq_documents_job"),
        UniqueConstraint(
            "document_id",
            "source_version",
            name="uq_documents_identity",
        ),
        UniqueConstraint(
            "document_id",
            "job_id",
            name="uq_documents_document_job",
        ),
    )

    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("jobs.job_id", ondelete="CASCADE"),
    )
    source_version: Mapped[str] = mapped_column(Text)
    source_name: Mapped[str] = mapped_column(Text)
    file_type: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)
    parser_name: Mapped[str] = mapped_column(Text)
    parser_version: Mapped[str] = mapped_column(Text)
    document_metadata: Mapped[dict[str, object]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    blocks: Mapped[list[DocumentBlockRow]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentBlockRow.block_index",
        passive_deletes=True,
    )
    runs: Mapped[list[VerificationRunRow]] = relationship(
        back_populates="document",
        passive_deletes=True,
    )


class DocumentBlockRow(Base):
    __tablename__ = "document_blocks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id"],
            ["documents.document_id"],
            name="fk_document_blocks_document",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "document_id",
            "block_id",
            name="uq_document_blocks_identity",
        ),
        UniqueConstraint(
            "document_id",
            "block_index",
            name="uq_document_blocks_order",
        ),
        CheckConstraint("block_index >= 0", name="ck_document_blocks_index"),
        CheckConstraint(
            "global_start >= 0 AND global_end >= global_start",
            name="ck_document_blocks_global_range",
        ),
        CheckConstraint(
            "block_start >= 0 AND block_end >= block_start",
            name="ck_document_blocks_local_range",
        ),
    )

    block_row_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    block_index: Mapped[int] = mapped_column(Integer)
    block_id: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(32))
    text: Mapped[str] = mapped_column(Text)
    global_start: Mapped[int] = mapped_column(Integer)
    global_end: Mapped[int] = mapped_column(Integer)
    block_start: Mapped[int] = mapped_column(Integer)
    block_end: Mapped[int] = mapped_column(Integer)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    paragraph_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    table_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    row_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cell_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bbox: Mapped[list[float] | None] = mapped_column(JSONB, nullable=True)
    parent_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    style: Mapped[dict[str, object]] = mapped_column(JSONB)
    source_locator: Mapped[dict[str, object]] = mapped_column(JSONB)
    document: Mapped[DocumentRow] = relationship(back_populates="blocks")


class VerificationRunRow(Base):
    __tablename__ = "verification_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "job_id"],
            ["documents.document_id", "documents.job_id"],
            name="fk_verification_runs_document_job",
            ondelete="CASCADE",
        ),
        UniqueConstraint("job_id", name="uq_verification_runs_job"),
        UniqueConstraint(
            "verification_run_id",
            "document_id",
            name="uq_verification_runs_run_document",
        ),
        CheckConstraint("stats_char_count >= 0", name="ck_runs_stats_char_count"),
        CheckConstraint(
            "stats_char_count_no_space >= 0",
            name="ck_runs_stats_char_count_no_space",
        ),
        CheckConstraint("stats_line_count >= 0", name="ck_runs_stats_line_count"),
        CheckConstraint(
            "stats_paragraph_count >= 0",
            name="ck_runs_stats_paragraph_count",
        ),
        CheckConstraint("stats_primary_count >= 0", name="ck_runs_stats_primary_count"),
        CheckConstraint("summary_total >= 0", name="ck_runs_summary_total"),
    )

    verification_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
    )
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("jobs.job_id", ondelete="CASCADE"),
    )
    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    scenario: Mapped[str] = mapped_column(String(32))
    execution_mode: Mapped[str] = mapped_column(String(32))
    analysis_mode: Mapped[str] = mapped_column(String(32))
    stats_char_count: Mapped[int] = mapped_column(Integer)
    stats_char_count_no_space: Mapped[int] = mapped_column(Integer)
    stats_line_count: Mapped[int] = mapped_column(Integer)
    stats_paragraph_count: Mapped[int] = mapped_column(Integer)
    stats_language: Mapped[str] = mapped_column(String(8))
    stats_primary_count: Mapped[int] = mapped_column(Integer)
    stats_primary_label: Mapped[str] = mapped_column(Text)
    summary_total: Mapped[int] = mapped_column(Integer)
    summary_by_type: Mapped[dict[str, int]] = mapped_column(JSONB)
    summary_by_severity: Mapped[dict[str, int]] = mapped_column(JSONB)
    summary_by_rule: Mapped[dict[str, int]] = mapped_column(JSONB)
    summary_by_layer: Mapped[dict[str, int]] = mapped_column(JSONB)
    summary_llm_review: Mapped[dict[str, object] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    dictionary_versions: Mapped[dict[str, str]] = mapped_column(JSONB)
    degradation_is_degraded: Mapped[bool] = mapped_column(Boolean)
    degradation_reasons: Mapped[list[str]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    document: Mapped[DocumentRow] = relationship(back_populates="runs")
    issues: Mapped[list[VerificationIssueRow]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="VerificationIssueRow.issue_index",
        passive_deletes=True,
    )
    review_revisions: Mapped[list[ReviewRevisionRow]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="ReviewRevisionRow.revision_number",
        passive_deletes=True,
    )
    export_artifacts: Mapped[list[ExportArtifactRow]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class VerificationIssueRow(Base):
    __tablename__ = "verification_issues"
    __table_args__ = (
        ForeignKeyConstraint(
            ["verification_run_id", "document_id"],
            [
                "verification_runs.verification_run_id",
                "verification_runs.document_id",
            ],
            name="fk_verification_issues_run_document",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["document_id", "block_id"],
            ["document_blocks.document_id", "document_blocks.block_id"],
            name="fk_verification_issues_document_block",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "verification_run_id",
            "issue_id",
            name="uq_verification_issues_run_issue",
        ),
        UniqueConstraint(
            "verification_run_id",
            "issue_index",
            name="uq_verification_issues_run_index",
        ),
        CheckConstraint("issue_index >= 0", name="ck_issues_issue_index"),
        CheckConstraint("start >= 0", name="ck_issues_start"),
        CheckConstraint('"end" > start', name="ck_issues_range"),
        CheckConstraint(
            "(block_start IS NULL AND block_end IS NULL) "
            "OR (block_start >= 0 AND block_end > block_start)",
            name="ck_issues_block_range",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_issues_confidence",
        ),
    )

    issue_row_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    verification_run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    issue_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    issue_index: Mapped[int] = mapped_column(Integer)
    block_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start: Mapped[int] = mapped_column(Integer)
    end: Mapped[int] = mapped_column(Integer)
    block_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    block_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    original: Mapped[str] = mapped_column(Text)
    suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    alternatives: Mapped[list[str]] = mapped_column(JSONB)
    type: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(16))
    layer: Mapped[str] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    rule_id: Mapped[str] = mapped_column(Text)
    rule_version: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    source_version: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    auto_fixable: Mapped[bool] = mapped_column(Boolean)
    context: Mapped[str] = mapped_column(Text)
    review: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    run: Mapped[VerificationRunRow] = relationship(back_populates="issues")


class ReviewRevisionRow(Base):
    __tablename__ = "review_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["verification_run_id", "document_id"],
            [
                "verification_runs.verification_run_id",
                "verification_runs.document_id",
            ],
            name="fk_review_revisions_run_document",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["document_id", "source_version"],
            ["documents.document_id", "documents.source_version"],
            name="fk_review_revisions_document_source",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "verification_run_id",
            "revision_number",
            name="uq_review_revisions_run_number",
        ),
        UniqueConstraint(
            "review_revision_id",
            "verification_run_id",
            name="uq_review_revisions_revision_run",
        ),
        CheckConstraint("revision_number > 0", name="ck_review_revisions_number"),
    )

    review_revision_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
    )
    verification_run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    source_version: Mapped[str] = mapped_column(Text)
    revision_number: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    run: Mapped[VerificationRunRow] = relationship(back_populates="review_revisions")


class ExportArtifactRow(Base):
    __tablename__ = "export_artifacts"
    __table_args__ = (
        Index(
            "ix_export_artifacts_status_reserved_at",
            "status",
            "reserved_at",
        ),
        ForeignKeyConstraint(
            ["verification_run_id"],
            ["verification_runs.verification_run_id"],
            name="fk_export_artifacts_run",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["review_revision_id", "verification_run_id"],
            [
                "review_revisions.review_revision_id",
                "review_revisions.verification_run_id",
            ],
            name="fk_export_artifacts_revision_run",
            ondelete="CASCADE",
        ),
        UniqueConstraint("storage_key", name="uq_export_artifacts_storage_key"),
        CheckConstraint("size_bytes >= 0", name="ck_export_artifacts_size"),
        CheckConstraint(
            "content_sha256 IS NULL "
            "OR content_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_export_artifacts_sha256",
        ),
        CheckConstraint(
            "status IN ('pending', 'ready')",
            name="ck_export_artifacts_status",
        ),
        CheckConstraint(
            "(status = 'pending' AND ready_at IS NULL) "
            "OR (status = 'ready' AND ready_at IS NOT NULL)",
            name="ck_export_artifacts_ready_state",
        ),
        CheckConstraint(
            "status <> 'pending' OR content_sha256 IS NOT NULL",
            name="ck_export_artifacts_pending_digest",
        ),
    )

    export_artifact_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
    )
    verification_run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    review_revision_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=True,
    )
    source_version: Mapped[str] = mapped_column(Text)
    file_type: Mapped[str] = mapped_column(String(16))
    file_name: Mapped[str] = mapped_column(Text)
    media_type: Mapped[str] = mapped_column(Text)
    storage_key: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16))
    reserved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ready_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    run: Mapped[VerificationRunRow] = relationship(back_populates="export_artifacts")
