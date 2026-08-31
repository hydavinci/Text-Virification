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
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class JobRow(Base):
    __tablename__ = "jobs"

    job_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    source_name: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(16))
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    events: Mapped[list[JobEventRow]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="JobEventRow.sequence",
        passive_deletes=True,
    )
    document: Mapped[DocumentRow | None] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    verification_run: Mapped[VerificationRunRow | None] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
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
    )

    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("jobs.job_id", ondelete="CASCADE"),
    )
    source_version: Mapped[str] = mapped_column(String(255))
    source_name: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    job: Mapped[JobRow] = relationship(back_populates="document")
    runs: Mapped[list[VerificationRunRow]] = relationship(
        back_populates="document",
        passive_deletes=True,
    )


class VerificationRunRow(Base):
    __tablename__ = "verification_runs"
    __table_args__ = (
        UniqueConstraint("job_id", name="uq_verification_runs_job"),
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
    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.document_id", ondelete="CASCADE"),
    )
    scenario: Mapped[str] = mapped_column(String(32))
    execution_mode: Mapped[str] = mapped_column(String(32))
    analysis_mode: Mapped[str] = mapped_column(String(32))
    stats_char_count: Mapped[int] = mapped_column(Integer)
    stats_char_count_no_space: Mapped[int] = mapped_column(Integer)
    stats_line_count: Mapped[int] = mapped_column(Integer)
    stats_paragraph_count: Mapped[int] = mapped_column(Integer)
    stats_language: Mapped[str] = mapped_column(String(8))
    stats_primary_count: Mapped[int] = mapped_column(Integer)
    stats_primary_label: Mapped[str] = mapped_column(String(64))
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
    job: Mapped[JobRow] = relationship(back_populates="verification_run")
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
    verification_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("verification_runs.verification_run_id", ondelete="CASCADE"),
    )
    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.document_id", ondelete="CASCADE"),
    )
    issue_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    issue_index: Mapped[int] = mapped_column(Integer)
    block_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start: Mapped[int] = mapped_column(Integer)
    end: Mapped[int] = mapped_column(Integer)
    block_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    block_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    original: Mapped[str] = mapped_column(Text)
    suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    alternatives: Mapped[list[str]] = mapped_column(JSONB)
    type: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(16))
    layer: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    rule_id: Mapped[str] = mapped_column(String(255))
    rule_version: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(255))
    source_version: Mapped[str] = mapped_column(String(255))
    confidence: Mapped[float] = mapped_column(Float)
    auto_fixable: Mapped[bool] = mapped_column(Boolean)
    context: Mapped[str] = mapped_column(Text)
    review: Mapped[str | None] = mapped_column(String(64), nullable=True)
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    run: Mapped[VerificationRunRow] = relationship(back_populates="issues")


class ReviewRevisionRow(Base):
    __tablename__ = "review_revisions"
    __table_args__ = (
        UniqueConstraint(
            "verification_run_id",
            "revision_number",
            name="uq_review_revisions_run_number",
        ),
        CheckConstraint("revision_number > 0", name="ck_review_revisions_number"),
    )

    review_revision_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
    )
    verification_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("verification_runs.verification_run_id", ondelete="CASCADE"),
    )
    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.document_id", ondelete="CASCADE"),
    )
    source_version: Mapped[str] = mapped_column(String(255))
    revision_number: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    run: Mapped[VerificationRunRow] = relationship(back_populates="review_revisions")
    export_artifacts: Mapped[list[ExportArtifactRow]] = relationship(
        back_populates="review_revision",
        passive_deletes=True,
    )


class ExportArtifactRow(Base):
    __tablename__ = "export_artifacts"
    __table_args__ = (
        UniqueConstraint("storage_key", name="uq_export_artifacts_storage_key"),
        CheckConstraint("size_bytes >= 0", name="ck_export_artifacts_size"),
    )

    export_artifact_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
    )
    verification_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("verification_runs.verification_run_id", ondelete="CASCADE"),
    )
    review_revision_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("review_revisions.review_revision_id", ondelete="CASCADE"),
        nullable=True,
    )
    source_version: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(16))
    file_name: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(512))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    run: Mapped[VerificationRunRow] = relationship(back_populates="export_artifacts")
    review_revision: Mapped[ReviewRevisionRow | None] = relationship(
        back_populates="export_artifacts"
    )
