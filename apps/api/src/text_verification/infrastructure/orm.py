from __future__ import annotations

from datetime import datetime
from uuid import UUID

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


class DocumentRow(Base):
    __tablename__ = "documents"

    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("jobs.job_id", ondelete="CASCADE"),
        primary_key=True,
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
        Index("ix_document_blocks_job_order", "job_id", "block_order", unique=True),
    )

    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.job_id", ondelete="CASCADE"),
        primary_key=True,
    )
    block_id: Mapped[str] = mapped_column(String(64), primary_key=True)
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
            ["job_id", "block_id"],
            ["document_blocks.job_id", "document_blocks.block_id"],
            ondelete="CASCADE",
        ),
        Index("ix_issues_job_category", "job_id", "category"),
        Index("ix_issues_job_severity", "job_id", "severity"),
        Index("ix_issues_job_block_start", "job_id", "block_id", "start_offset"),
    )

    issue_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.job_id", ondelete="CASCADE"),
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


class IssueDecisionRow(Base):
    __tablename__ = "issue_decisions"
    __table_args__ = (
        CheckConstraint(
            """
            (
                action = 'custom'
                AND replacement IS NOT NULL
                AND btrim(replacement) <> ''
            )
            OR (
                action IN ('accepted', 'ignored')
                AND replacement IS NULL
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
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("jobs.job_id", ondelete="CASCADE"),
    )
    issue_version: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(16))
    replacement: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CheckerFailureRow(Base):
    __tablename__ = "checker_failures"

    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.job_id", ondelete="CASCADE"),
        primary_key=True,
    )
    category: Mapped[str] = mapped_column(String(32), primary_key=True)
    code: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
