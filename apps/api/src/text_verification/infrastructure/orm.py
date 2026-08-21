from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
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
    text,
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
    scenario: Mapped[str] = mapped_column(String(32), default="general")
    enabled_categories_json: Mapped[list[str]] = mapped_column("enabled_categories", JSONB)
    active_version_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "document_versions.version_id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_jobs_active_version_id",
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    events: Mapped[list[JobEventRow]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="JobEventRow.sequence",
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
    metadata_json: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    job: Mapped[JobRow] = relationship(back_populates="events")


class DocumentVersionRow(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        CheckConstraint(
            """
            (
                status = 'failed'
                AND failure_code IS NOT NULL
                AND failure_message IS NOT NULL
            )
            OR (
                status IN ('queued', 'analyzing', 'succeeded')
                AND failure_code IS NULL
                AND failure_message IS NULL
            )
            """,
            name="ck_document_versions_status_failure",
        ),
        Index(
            "ix_document_versions_job_revision_number",
            "job_id",
            "revision_number",
            unique=True,
        ),
        Index(
            "ix_document_versions_job_idempotency_key",
            "job_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("jobs.job_id", ondelete="CASCADE"),
    )
    parent_version_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("document_versions.version_id", ondelete="SET NULL"),
        nullable=True,
    )
    revision_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), index=True)
    source_kind: Mapped[str] = mapped_column(String(32))
    created_reason: Mapped[str] = mapped_column(String(32))
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    events: Mapped[list[DocumentVersionEventRow]] = relationship(
        back_populates="version",
        cascade="all, delete-orphan",
        order_by="DocumentVersionEventRow.sequence",
    )


class DocumentVersionEventRow(Base):
    __tablename__ = "document_version_events"
    __table_args__ = (
        Index(
            "ix_document_version_events_version_sequence",
            "version_id",
            "sequence",
            unique=True,
        ),
    )

    event_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("document_versions.version_id", ondelete="CASCADE"),
    )
    sequence: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32))
    progress: Mapped[int] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(String(255))
    metadata_json: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[DocumentVersionRow] = relationship(back_populates="events")


class DocumentRow(Base):
    __tablename__ = "documents"
    __table_args__ = (Index("ix_documents_job_id", "job_id"),)

    version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("document_versions.version_id", ondelete="CASCADE"),
        primary_key=True,
    )
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("jobs.job_id", ondelete="CASCADE"),
    )
    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    version: Mapped[int] = mapped_column(Integer)
    file_type: Mapped[str] = mapped_column(String(16))
    source_name: Mapped[str] = mapped_column(String(255))
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSONB)
    blocks: Mapped[list[DocumentBlockRow]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentBlockRow.block_order",
    )


class DocumentBlockRow(Base):
    __tablename__ = "document_blocks"
    __table_args__ = (
        Index("ix_document_blocks_version_order", "version_id", "block_order", unique=True),
    )

    version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.version_id", ondelete="CASCADE"),
        primary_key=True,
    )
    block_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("jobs.job_id", ondelete="CASCADE"),
    )
    block_order: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32))
    text: Mapped[str] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    paragraph_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    style_json: Mapped[dict[str, object]] = mapped_column(JSONB)
    source_locator_json: Mapped[dict[str, object]] = mapped_column(JSONB)
    document: Mapped[DocumentRow] = relationship(back_populates="blocks")


class IssueRow(Base):
    __tablename__ = "issues"
    __table_args__ = (
        ForeignKeyConstraint(
            ["version_id", "block_id"],
            ["document_blocks.version_id", "document_blocks.block_id"],
            ondelete="CASCADE",
        ),
        Index("ix_issues_version_category", "version_id", "category"),
        Index("ix_issues_version_severity", "version_id", "severity"),
        Index("ix_issues_version_block_start", "version_id", "block_id", "start_offset"),
    )

    issue_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("document_versions.version_id", ondelete="CASCADE"),
    )
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("jobs.job_id", ondelete="CASCADE"),
    )
    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    document_version: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(16))
    rule_id: Mapped[str] = mapped_column(String(128))
    block_id: Mapped[str] = mapped_column(String(64))
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_offset: Mapped[int] = mapped_column(Integer)
    end_offset: Mapped[int] = mapped_column(Integer)
    original: Mapped[str] = mapped_column(Text)
    suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    alternatives_json: Mapped[list[str]] = mapped_column(JSONB)
    issue_type: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(64))
    source_version: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[float] = mapped_column(Float)
    auto_fixable: Mapped[bool] = mapped_column(Boolean)
    context: Mapped[str] = mapped_column(Text)


class EditDraftRow(Base):
    __tablename__ = "edit_drafts"
    __table_args__ = (
        Index(
            "ix_edit_drafts_job_base_version_active",
            "job_id",
            "base_version_id",
            unique=True,
            postgresql_where=text("consumed_at IS NULL"),
        ),
    )

    draft_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("jobs.job_id", ondelete="CASCADE"),
    )
    base_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("document_versions.version_id", ondelete="CASCADE"),
    )
    revision: Mapped[int] = mapped_column(Integer, default=1)
    blocks_json: Mapped[list[dict[str, object]]] = mapped_column(JSONB)
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def blocks(self) -> list[dict[str, object]]:
        return self.blocks_json


class IssueSuggestionRow(Base):
    __tablename__ = "issue_suggestions"
    __table_args__ = (
        Index("ix_issue_suggestions_issue_rank", "issue_id", "rank", unique=True),
        Index(
            "ix_issue_suggestions_issue_preferred",
            "issue_id",
            unique=True,
            postgresql_where=text("preferred"),
        ),
    )

    suggestion_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    issue_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("issues.issue_id", ondelete="CASCADE"),
    )
    version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("document_versions.version_id", ondelete="CASCADE"),
    )
    text: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32))
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    rank: Mapped[int] = mapped_column(Integer)
    preferred: Mapped[bool] = mapped_column(Boolean, default=False)


class ReviewOperationBatchRow(Base):
    __tablename__ = "review_operation_batches"
    __table_args__ = (
        Index(
            "ix_review_operation_batches_job_version_created_at",
            "job_id",
            "version_id",
            "created_at",
            "operation_batch_id",
        ),
    )

    operation_batch_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("jobs.job_id", ondelete="CASCADE"),
    )
    version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("document_versions.version_id", ondelete="CASCADE"),
    )
    operation_type: Mapped[str] = mapped_column(String(32))
    affected_count: Mapped[int] = mapped_column(Integer)
    undoes_batch_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("review_operation_batches.operation_batch_id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    items: Mapped[list[ReviewOperationItemRow]] = relationship(
        back_populates="batch",
        cascade="all, delete-orphan",
        order_by="ReviewOperationItemRow.sequence",
    )

    @property
    def batch_id(self) -> UUID:
        return self.operation_batch_id


class ReviewOperationItemRow(Base):
    __tablename__ = "review_operation_items"
    __table_args__ = (
        CheckConstraint(
            "before_json IS NOT NULL OR after_json IS NOT NULL",
            name="ck_review_operation_items_snapshot",
        ),
        Index(
            "ix_review_operation_items_batch_sequence",
            "operation_batch_id",
            "sequence",
            unique=True,
        ),
    )

    operation_batch_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("review_operation_batches.operation_batch_id", ondelete="CASCADE"),
        primary_key=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    issue_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("issues.issue_id", ondelete="CASCADE"),
    )
    before_json: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    after_json: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    batch: Mapped[ReviewOperationBatchRow] = relationship(back_populates="items")


class IssueDecisionRow(Base):
    __tablename__ = "issue_decisions"
    __table_args__ = (
        CheckConstraint(
            """
            (
                action = 'accepted'
                AND COALESCE(final_replacement, replacement) IS NOT NULL
                AND COALESCE(final_replacement, replacement) ~ '[^[:space:]]'
            )
            OR (
                action = 'ignored'
                AND final_replacement IS NULL
                AND replacement IS NULL
                AND suggestion_id IS NULL
            )
            """,
            name="ck_issue_decisions_action_replacement",
        ),
        Index("ix_issue_decisions_job_action", "job_id", "action"),
    )

    issue_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("issues.issue_id", ondelete="CASCADE"),
        primary_key=True,
    )
    version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("document_versions.version_id", ondelete="CASCADE"),
    )
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("jobs.job_id", ondelete="CASCADE"),
    )
    issue_version: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    action: Mapped[str] = mapped_column(String(16))
    replacement: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_replacement: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggestion_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("issue_suggestions.suggestion_id", ondelete="SET NULL"),
        nullable=True,
    )
    operation_batch_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("review_operation_batches.operation_batch_id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ExportRow(Base):
    __tablename__ = "exports"
    __table_args__ = (
        CheckConstraint(
            """
            (
                status = 'failed'
                AND error_code IS NOT NULL
                AND error_message IS NOT NULL
            )
            OR (
                status IN ('queued', 'processing', 'completed')
                AND error_code IS NULL
                AND error_message IS NULL
            )
            """,
            name="ck_exports_status_error",
        ),
        Index("ix_exports_job_created_at", "job_id", "created_at"),
        Index(
            "ix_exports_recoverable_updated_at",
            "status",
            "updated_at",
            "export_id",
            postgresql_where=text("status IN ('queued', 'processing')"),
        ),
    )

    export_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("jobs.job_id", ondelete="CASCADE"),
    )
    version_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("document_versions.version_id", ondelete="SET NULL"),
        nullable=True,
    )
    export_type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    file_name: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(255))
    warnings_json: Mapped[list[object]] = mapped_column("warnings", JSONB)
    snapshot_json: Mapped[dict[str, object] | None] = mapped_column(
        "snapshot",
        JSONB,
        nullable=True,
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CheckerFailureRow(Base):
    __tablename__ = "checker_failures"

    version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("document_versions.version_id", ondelete="CASCADE"),
        primary_key=True,
    )
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("jobs.job_id", ondelete="CASCADE"),
    )
    category: Mapped[str] = mapped_column(String(32), primary_key=True)
    code: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
