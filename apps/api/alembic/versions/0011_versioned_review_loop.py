"""add versioned review loop schema

Revision ID: 0011_versioned_review_loop
Revises: 0010_export_snapshots
Create Date: 2026-08-21 10:30:00
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "0011_versioned_review_loop"
down_revision = "0010_export_snapshots"
branch_labels = None
depends_on = None

UUIDType = postgresql.UUID(as_uuid=True)
JSONBType = postgresql.JSONB(astext_type=sa.Text())

DOCUMENT_VERSIONS_TABLE = sa.table(
    "document_versions",
    sa.column("version_id", UUIDType),
    sa.column("job_id", UUIDType),
    sa.column("parent_version_id", UUIDType),
    sa.column("revision_number", sa.Integer()),
    sa.column("status", sa.String(length=32)),
    sa.column("source_kind", sa.String(length=32)),
    sa.column("created_reason", sa.String(length=32)),
    sa.column("content_sha256", sa.String(length=64)),
    sa.column("idempotency_key", sa.String(length=255)),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("started_at", sa.DateTime(timezone=True)),
    sa.column("completed_at", sa.DateTime(timezone=True)),
    sa.column("failure_code", sa.String(length=64)),
    sa.column("failure_message", sa.Text()),
)
DOCUMENTS_NEW_TABLE = sa.table(
    "documents_new",
    sa.column("version_id", UUIDType),
    sa.column("job_id", UUIDType),
    sa.column("document_id", UUIDType),
    sa.column("version", sa.Integer()),
    sa.column("file_type", sa.String(length=16)),
    sa.column("source_name", sa.String(length=255)),
    sa.column("metadata_json", JSONBType),
)
DOCUMENT_BLOCKS_NEW_TABLE = sa.table(
    "document_blocks_new",
    sa.column("version_id", UUIDType),
    sa.column("block_id", sa.String(length=64)),
    sa.column("job_id", UUIDType),
    sa.column("block_order", sa.Integer()),
    sa.column("kind", sa.String(length=32)),
    sa.column("text", sa.Text()),
    sa.column("page", sa.Integer()),
    sa.column("paragraph_index", sa.Integer()),
    sa.column("parent_id", sa.String(length=64)),
    sa.column("style_json", JSONBType),
    sa.column("source_locator_json", JSONBType),
)
ISSUES_NEW_TABLE = sa.table(
    "issues_new",
    sa.column("issue_id", UUIDType),
    sa.column("version_id", UUIDType),
    sa.column("job_id", UUIDType),
    sa.column("document_id", UUIDType),
    sa.column("document_version", sa.Integer()),
    sa.column("category", sa.String(length=32)),
    sa.column("severity", sa.String(length=16)),
    sa.column("rule_id", sa.String(length=128)),
    sa.column("block_id", sa.String(length=64)),
    sa.column("page", sa.Integer()),
    sa.column("start_offset", sa.Integer()),
    sa.column("end_offset", sa.Integer()),
    sa.column("original", sa.Text()),
    sa.column("suggestion", sa.Text()),
    sa.column("alternatives_json", JSONBType),
    sa.column("issue_type", sa.String(length=64)),
    sa.column("message", sa.Text()),
    sa.column("source", sa.String(length=64)),
    sa.column("source_version", sa.String(length=32)),
    sa.column("confidence", sa.Float()),
    sa.column("auto_fixable", sa.Boolean()),
    sa.column("context", sa.Text()),
)
CHECKER_FAILURES_NEW_TABLE = sa.table(
    "checker_failures_new",
    sa.column("version_id", UUIDType),
    sa.column("job_id", UUIDType),
    sa.column("category", sa.String(length=32)),
    sa.column("code", sa.String(length=64)),
    sa.column("message", sa.Text()),
)
ISSUE_SUGGESTIONS_NEW_TABLE = sa.table(
    "issue_suggestions_new",
    sa.column("suggestion_id", UUIDType),
    sa.column("issue_id", UUIDType),
    sa.column("version_id", UUIDType),
    sa.column("text", sa.Text()),
    sa.column("source", sa.String(length=32)),
    sa.column("explanation", sa.Text()),
    sa.column("rank", sa.Integer()),
    sa.column("preferred", sa.Boolean()),
)
ISSUE_DECISIONS_NEW_TABLE = sa.table(
    "issue_decisions_new",
    sa.column("issue_id", UUIDType),
    sa.column("version_id", UUIDType),
    sa.column("job_id", UUIDType),
    sa.column("issue_version", sa.Integer()),
    sa.column("revision", sa.Integer()),
    sa.column("action", sa.String(length=16)),
    sa.column("replacement", sa.Text()),
    sa.column("final_replacement", sa.Text()),
    sa.column("suggestion_id", UUIDType),
    sa.column("operation_batch_id", UUIDType),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)
DOCUMENTS_LEGACY_TABLE = sa.table(
    "documents_legacy",
    sa.column("job_id", UUIDType),
    sa.column("document_id", UUIDType),
    sa.column("version", sa.Integer()),
    sa.column("file_type", sa.String(length=16)),
    sa.column("source_name", sa.String(length=255)),
    sa.column("metadata_json", JSONBType),
)
DOCUMENT_BLOCKS_LEGACY_TABLE = sa.table(
    "document_blocks_legacy",
    sa.column("job_id", UUIDType),
    sa.column("block_id", sa.String(length=64)),
    sa.column("block_order", sa.Integer()),
    sa.column("kind", sa.String(length=32)),
    sa.column("text", sa.Text()),
    sa.column("page", sa.Integer()),
    sa.column("paragraph_index", sa.Integer()),
    sa.column("parent_id", sa.String(length=64)),
    sa.column("style_json", JSONBType),
    sa.column("source_locator_json", JSONBType),
)
ISSUES_LEGACY_TABLE = sa.table(
    "issues_legacy",
    sa.column("issue_id", UUIDType),
    sa.column("job_id", UUIDType),
    sa.column("document_id", UUIDType),
    sa.column("document_version", sa.Integer()),
    sa.column("category", sa.String(length=32)),
    sa.column("severity", sa.String(length=16)),
    sa.column("rule_id", sa.String(length=128)),
    sa.column("block_id", sa.String(length=64)),
    sa.column("page", sa.Integer()),
    sa.column("start_offset", sa.Integer()),
    sa.column("end_offset", sa.Integer()),
    sa.column("original", sa.Text()),
    sa.column("suggestion", sa.Text()),
    sa.column("alternatives_json", JSONBType),
    sa.column("issue_type", sa.String(length=64)),
    sa.column("message", sa.Text()),
    sa.column("source", sa.String(length=64)),
    sa.column("source_version", sa.String(length=32)),
    sa.column("confidence", sa.Float()),
    sa.column("auto_fixable", sa.Boolean()),
    sa.column("context", sa.Text()),
)
CHECKER_FAILURES_LEGACY_TABLE = sa.table(
    "checker_failures_legacy",
    sa.column("job_id", UUIDType),
    sa.column("category", sa.String(length=32)),
    sa.column("code", sa.String(length=64)),
    sa.column("message", sa.Text()),
)
ISSUE_DECISIONS_LEGACY_TABLE = sa.table(
    "issue_decisions_legacy",
    sa.column("issue_id", UUIDType),
    sa.column("job_id", UUIDType),
    sa.column("issue_version", sa.Integer()),
    sa.column("action", sa.String(length=16)),
    sa.column("replacement", sa.Text()),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    bind = op.get_bind()

    _create_document_versions_table()
    _create_document_version_events_table()
    _create_edit_drafts_table()
    _create_review_operation_batches_table()
    op.add_column("jobs", sa.Column("active_version_id", UUIDType, nullable=True))
    op.create_foreign_key(
        "fk_jobs_active_version_id",
        "jobs",
        "document_versions",
        ["active_version_id"],
        ["version_id"],
        ondelete="SET NULL",
    )
    op.add_column("exports", sa.Column("version_id", UUIDType, nullable=True))
    op.create_foreign_key(
        "fk_exports_version_id",
        "exports",
        "document_versions",
        ["version_id"],
        ["version_id"],
        ondelete="SET NULL",
    )
    _create_documents_new_table()
    _create_document_blocks_new_table()
    _create_issues_new_table()
    _create_checker_failures_new_table()
    _create_issue_suggestions_new_table()
    _create_review_operation_items_table()
    _create_issue_decisions_new_table()

    document_rows = list(
        bind.execute(
            sa.text(
                """
                SELECT
                    d.job_id,
                    d.document_id,
                    d.version,
                    d.file_type,
                    d.source_name,
                    d.metadata_json,
                    j.created_at AS job_created_at,
                    j.updated_at AS job_updated_at
                FROM documents AS d
                JOIN jobs AS j ON j.job_id = d.job_id
                ORDER BY d.job_id
                """
            )
        ).mappings()
    )
    block_rows = list(
        bind.execute(
            sa.text(
                """
                SELECT
                    job_id,
                    block_id,
                    block_order,
                    kind,
                    text,
                    page,
                    paragraph_index,
                    parent_id,
                    style_json,
                    source_locator_json
                FROM document_blocks
                ORDER BY job_id, block_order, block_id
                """
            )
        ).mappings()
    )
    issue_rows = list(
        bind.execute(
            sa.text(
                """
                SELECT
                    issue_id,
                    job_id,
                    document_id,
                    document_version,
                    category,
                    severity,
                    rule_id,
                    block_id,
                    page,
                    start_offset,
                    end_offset,
                    original,
                    suggestion,
                    alternatives_json,
                    issue_type,
                    message,
                    source,
                    source_version,
                    confidence,
                    auto_fixable,
                    context
                FROM issues
                ORDER BY issue_id
                """
            )
        ).mappings()
    )
    checker_failure_rows = list(
        bind.execute(
            sa.text(
                """
                SELECT job_id, category, code, message
                FROM checker_failures
                ORDER BY job_id, category
                """
            )
        ).mappings()
    )
    decision_rows = list(
        bind.execute(
            sa.text(
                """
                SELECT issue_id, job_id, issue_version, action, replacement, updated_at
                FROM issue_decisions
                ORDER BY issue_id
                """
            )
        ).mappings()
    )

    version_rows, version_ids_by_job = _build_version_rows(document_rows)
    if version_rows:
        op.bulk_insert(DOCUMENT_VERSIONS_TABLE, version_rows)

    if document_rows:
        op.bulk_insert(
            DOCUMENTS_NEW_TABLE,
            [
                {
                    "version_id": version_ids_by_job[row["job_id"]],
                    "job_id": row["job_id"],
                    "document_id": row["document_id"],
                    "version": row["version"],
                    "file_type": row["file_type"],
                    "source_name": row["source_name"],
                    "metadata_json": row["metadata_json"],
                }
                for row in document_rows
            ],
        )
    if block_rows:
        op.bulk_insert(
            DOCUMENT_BLOCKS_NEW_TABLE,
            [
                {
                    "version_id": version_ids_by_job[row["job_id"]],
                    "block_id": row["block_id"],
                    "job_id": row["job_id"],
                    "block_order": row["block_order"],
                    "kind": row["kind"],
                    "text": row["text"],
                    "page": row["page"],
                    "paragraph_index": row["paragraph_index"],
                    "parent_id": row["parent_id"],
                    "style_json": row["style_json"],
                    "source_locator_json": row["source_locator_json"],
                }
                for row in block_rows
            ],
        )
    if issue_rows:
        op.bulk_insert(
            ISSUES_NEW_TABLE,
            [
                {
                    "issue_id": row["issue_id"],
                    "version_id": version_ids_by_job[row["job_id"]],
                    "job_id": row["job_id"],
                    "document_id": row["document_id"],
                    "document_version": row["document_version"],
                    "category": row["category"],
                    "severity": row["severity"],
                    "rule_id": row["rule_id"],
                    "block_id": row["block_id"],
                    "page": row["page"],
                    "start_offset": row["start_offset"],
                    "end_offset": row["end_offset"],
                    "original": row["original"],
                    "suggestion": row["suggestion"],
                    "alternatives_json": row["alternatives_json"],
                    "issue_type": row["issue_type"],
                    "message": row["message"],
                    "source": row["source"],
                    "source_version": row["source_version"],
                    "confidence": row["confidence"],
                    "auto_fixable": row["auto_fixable"],
                    "context": row["context"],
                }
                for row in issue_rows
            ],
        )
    if checker_failure_rows:
        op.bulk_insert(
            CHECKER_FAILURES_NEW_TABLE,
            [
                {
                    "version_id": version_ids_by_job[row["job_id"]],
                    "job_id": row["job_id"],
                    "category": row["category"],
                    "code": row["code"],
                    "message": row["message"],
                }
                for row in checker_failure_rows
            ],
        )

    issue_rows_by_id = {row["issue_id"]: row for row in issue_rows}
    suggestion_rows: list[dict[str, Any]] = []
    preferred_suggestions: dict[UUID, tuple[UUID, str]] = {}
    for row in issue_rows:
        ordered_suggestions = _ordered_unique_suggestions(
            row["suggestion"],
            row["alternatives_json"] or [],
        )
        if not ordered_suggestions:
            continue
        version_id = version_ids_by_job[row["job_id"]]
        for rank, text_value in enumerate(ordered_suggestions):
            suggestion_id = uuid4()
            suggestion_rows.append(
                {
                    "suggestion_id": suggestion_id,
                    "issue_id": row["issue_id"],
                    "version_id": version_id,
                    "text": text_value,
                    "source": "rule",
                    "explanation": None,
                    "rank": rank,
                    "preferred": rank == 0,
                }
            )
            if rank == 0:
                preferred_suggestions[row["issue_id"]] = (suggestion_id, text_value)
    if suggestion_rows:
        op.bulk_insert(ISSUE_SUGGESTIONS_NEW_TABLE, suggestion_rows)

    decision_inserts: list[dict[str, Any]] = []
    for row in decision_rows:
        issue_row = issue_rows_by_id[row["issue_id"]]
        preferred = preferred_suggestions.get(row["issue_id"])
        preferred_suggestion_id = preferred[0] if preferred is not None else None
        preferred_text = preferred[1] if preferred is not None else None
        legacy_replacement = row["replacement"]
        if row["action"] == "custom":
            action = "accepted"
            final_replacement = legacy_replacement
            suggestion_id = None
        elif row["action"] == "accepted":
            final_replacement = (
                preferred_text
                or legacy_replacement
                or issue_row["suggestion"]
                or issue_row["original"]
            )
            action = "accepted"
            suggestion_id = (
                preferred_suggestion_id if preferred_text == final_replacement else None
            )
        else:
            action = "ignored"
            final_replacement = None
            suggestion_id = None
            legacy_replacement = None

        decision_inserts.append(
            {
                "issue_id": row["issue_id"],
                "version_id": version_ids_by_job[row["job_id"]],
                "job_id": row["job_id"],
                "issue_version": row["issue_version"],
                "revision": 0,
                "action": action,
                "replacement": final_replacement if action == "accepted" else None,
                "final_replacement": final_replacement,
                "suggestion_id": suggestion_id,
                "operation_batch_id": None,
                "updated_at": row["updated_at"],
            }
        )
    if decision_inserts:
        op.bulk_insert(ISSUE_DECISIONS_NEW_TABLE, decision_inserts)

    for job_id, version_id in version_ids_by_job.items():
        bind.execute(
            sa.text(
                """
                UPDATE jobs
                SET active_version_id = :version_id
                WHERE job_id = :job_id
                """
            ),
            {"job_id": job_id, "version_id": version_id},
        )
        bind.execute(
            sa.text(
                """
                UPDATE exports
                SET version_id = :version_id
                WHERE job_id = :job_id
                """
            ),
            {"job_id": job_id, "version_id": version_id},
        )

    op.drop_table("issue_decisions")
    op.drop_table("checker_failures")
    op.drop_table("issues")
    op.drop_table("document_blocks")
    op.drop_table("documents")

    op.rename_table("documents_new", "documents")
    op.rename_table("document_blocks_new", "document_blocks")
    op.rename_table("issues_new", "issues")
    op.rename_table("checker_failures_new", "checker_failures")
    op.rename_table("issue_suggestions_new", "issue_suggestions")
    op.rename_table("issue_decisions_new", "issue_decisions")

    op.create_index(
        "ix_issue_decisions_job_action",
        "issue_decisions",
        ["job_id", "action"],
        unique=False,
    )
    op.execute(
        sa.text(
            """
            ALTER TABLE issue_decisions
            RENAME CONSTRAINT ck_issue_decisions_action_replacement_new
            TO ck_issue_decisions_action_replacement
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()

    active_document_rows = list(
        bind.execute(
            sa.text(
                """
                SELECT
                    d.version_id,
                    d.job_id,
                    d.document_id,
                    d.version,
                    d.file_type,
                    d.source_name,
                    d.metadata_json
                FROM documents AS d
                JOIN jobs AS j ON j.active_version_id = d.version_id
                ORDER BY d.job_id
                """
            )
        ).mappings()
    )
    active_version_ids = {row["version_id"] for row in active_document_rows}
    if active_version_ids:
        active_blocks = list(
            bind.execute(
                sa.text(
                    """
                    SELECT
                        version_id,
                        block_id,
                        job_id,
                        block_order,
                        kind,
                        text,
                        page,
                        paragraph_index,
                        parent_id,
                        style_json,
                        source_locator_json
                    FROM document_blocks
                    WHERE version_id = ANY(:version_ids)
                    ORDER BY job_id, block_order, block_id
                    """
                ),
                {"version_ids": list(active_version_ids)},
            ).mappings()
        )
        active_issues = list(
            bind.execute(
                sa.text(
                    """
                    SELECT
                        issue_id,
                        version_id,
                        job_id,
                        document_id,
                        document_version,
                        category,
                        severity,
                        rule_id,
                        block_id,
                        page,
                        start_offset,
                        end_offset,
                        original,
                        suggestion,
                        alternatives_json,
                        issue_type,
                        message,
                        source,
                        source_version,
                        confidence,
                        auto_fixable,
                        context
                    FROM issues
                    WHERE version_id = ANY(:version_ids)
                    ORDER BY issue_id
                    """
                ),
                {"version_ids": list(active_version_ids)},
            ).mappings()
        )
        active_failures = list(
            bind.execute(
                sa.text(
                    """
                    SELECT version_id, job_id, category, code, message
                    FROM checker_failures
                    WHERE version_id = ANY(:version_ids)
                    ORDER BY job_id, category
                    """
                ),
                {"version_ids": list(active_version_ids)},
            ).mappings()
        )
        active_decisions = list(
            bind.execute(
                sa.text(
                    """
                    SELECT
                        issue_id,
                        version_id,
                        job_id,
                        issue_version,
                        action,
                        replacement,
                        final_replacement,
                        suggestion_id,
                        updated_at
                    FROM issue_decisions
                    WHERE version_id = ANY(:version_ids)
                    ORDER BY issue_id
                    """
                ),
                {"version_ids": list(active_version_ids)},
            ).mappings()
        )
    else:
        active_blocks = []
        active_issues = []
        active_failures = []
        active_decisions = []

    _create_documents_legacy_table()
    _create_document_blocks_legacy_table()
    _create_issues_legacy_table()
    _create_checker_failures_legacy_table()

    if active_document_rows:
        op.bulk_insert(
            DOCUMENTS_LEGACY_TABLE,
            [
                {
                    "job_id": row["job_id"],
                    "document_id": row["document_id"],
                    "version": row["version"],
                    "file_type": row["file_type"],
                    "source_name": row["source_name"],
                    "metadata_json": row["metadata_json"],
                }
                for row in active_document_rows
            ],
        )
    if active_blocks:
        op.bulk_insert(
            DOCUMENT_BLOCKS_LEGACY_TABLE,
            [
                {
                    "job_id": row["job_id"],
                    "block_id": row["block_id"],
                    "block_order": row["block_order"],
                    "kind": row["kind"],
                    "text": row["text"],
                    "page": row["page"],
                    "paragraph_index": row["paragraph_index"],
                    "parent_id": row["parent_id"],
                    "style_json": row["style_json"],
                    "source_locator_json": row["source_locator_json"],
                }
                for row in active_blocks
            ],
        )
    if active_issues:
        op.bulk_insert(
            ISSUES_LEGACY_TABLE,
            [
                {
                    "issue_id": row["issue_id"],
                    "job_id": row["job_id"],
                    "document_id": row["document_id"],
                    "document_version": row["document_version"],
                    "category": row["category"],
                    "severity": row["severity"],
                    "rule_id": row["rule_id"],
                    "block_id": row["block_id"],
                    "page": row["page"],
                    "start_offset": row["start_offset"],
                    "end_offset": row["end_offset"],
                    "original": row["original"],
                    "suggestion": row["suggestion"],
                    "alternatives_json": row["alternatives_json"],
                    "issue_type": row["issue_type"],
                    "message": row["message"],
                    "source": row["source"],
                    "source_version": row["source_version"],
                    "confidence": row["confidence"],
                    "auto_fixable": row["auto_fixable"],
                    "context": row["context"],
                }
                for row in active_issues
            ],
        )
    if active_failures:
        op.bulk_insert(
            CHECKER_FAILURES_LEGACY_TABLE,
            [
                {
                    "job_id": row["job_id"],
                    "category": row["category"],
                    "code": row["code"],
                    "message": row["message"],
                }
                for row in active_failures
            ],
        )

    active_issues_by_id = {row["issue_id"]: row for row in active_issues}
    legacy_decision_rows: list[dict[str, Any]] = []
    for row in active_decisions:
        issue_row = active_issues_by_id[row["issue_id"]]
        final_replacement = row["final_replacement"] or row["replacement"]
        if row["action"] == "ignored":
            action = "ignored"
            replacement = None
        elif issue_row["suggestion"] is not None and final_replacement == issue_row["suggestion"]:
            action = "accepted"
            replacement = None
        else:
            action = "custom"
            replacement = final_replacement

        legacy_decision_rows.append(
            {
                "issue_id": row["issue_id"],
                "job_id": row["job_id"],
                "issue_version": row["issue_version"],
                "action": action,
                "replacement": replacement,
                "updated_at": row["updated_at"],
            }
        )

    op.drop_table("issue_decisions")
    _create_issue_decisions_legacy_table()
    if legacy_decision_rows:
        op.bulk_insert(ISSUE_DECISIONS_LEGACY_TABLE, legacy_decision_rows)

    op.drop_table("issue_suggestions")
    op.drop_table("review_operation_items")
    op.drop_table("review_operation_batches")
    op.drop_table("edit_drafts")
    op.drop_table("document_version_events")
    op.drop_table("checker_failures")
    op.drop_table("issues")
    op.drop_table("document_blocks")
    op.drop_table("documents")

    op.rename_table("documents_legacy", "documents")
    op.rename_table("document_blocks_legacy", "document_blocks")
    op.rename_table("issues_legacy", "issues")
    op.rename_table("checker_failures_legacy", "checker_failures")
    op.rename_table("issue_decisions_legacy", "issue_decisions")

    op.drop_constraint("fk_exports_version_id", "exports", type_="foreignkey")
    op.drop_column("exports", "version_id")
    op.drop_constraint("fk_jobs_active_version_id", "jobs", type_="foreignkey")
    op.drop_column("jobs", "active_version_id")
    op.drop_table("document_versions")


def _build_version_rows(
    document_rows: Sequence[Any],
) -> tuple[list[dict[str, Any]], dict[UUID, UUID]]:
    version_rows: list[dict[str, Any]] = []
    version_ids_by_job: dict[UUID, UUID] = {}
    for row in document_rows:
        version_id = uuid4()
        version_ids_by_job[row["job_id"]] = version_id
        version_rows.append(
            {
                "version_id": version_id,
                "job_id": row["job_id"],
                "parent_version_id": None,
                "revision_number": 1,
                "status": "succeeded",
                "source_kind": "upload",
                "created_reason": "upload",
                "content_sha256": None,
                "idempotency_key": None,
                "created_at": row["job_created_at"],
                "started_at": row["job_updated_at"],
                "completed_at": row["job_updated_at"],
                "failure_code": None,
                "failure_message": None,
            }
        )
    return version_rows, version_ids_by_job


def _ordered_unique_suggestions(
    suggestion: str | None,
    alternatives: Iterable[str],
) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in ([suggestion] if suggestion is not None else []) + list(alternatives):
        if not value.strip():
            continue
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _create_document_versions_table() -> None:
    op.create_table(
        "document_versions",
        sa.Column("version_id", UUIDType, primary_key=True, nullable=False),
        sa.Column("job_id", UUIDType, nullable=False),
        sa.Column("parent_version_id", UUIDType, nullable=True),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("created_reason", sa.String(length=32), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.CheckConstraint(
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
        sa.ForeignKeyConstraint(["job_id"], ["jobs.job_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["parent_version_id"],
            ["document_versions.version_id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_document_versions_job_revision_number",
        "document_versions",
        ["job_id", "revision_number"],
        unique=True,
    )
    op.create_index(
        "ix_document_versions_job_idempotency_key",
        "document_versions",
        ["job_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def _create_document_version_events_table() -> None:
    op.create_table(
        "document_version_events",
        sa.Column("event_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("version_id", UUIDType, nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("message", sa.String(length=255), nullable=False),
        sa.Column("metadata_json", JSONBType, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["document_versions.version_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_document_version_events_version_sequence",
        "document_version_events",
        ["version_id", "sequence"],
        unique=True,
    )


def _create_edit_drafts_table() -> None:
    op.create_table(
        "edit_drafts",
        sa.Column("draft_id", UUIDType, primary_key=True, nullable=False),
        sa.Column("job_id", UUIDType, nullable=False),
        sa.Column("base_version_id", UUIDType, nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("blocks_json", JSONBType, nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.job_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["base_version_id"],
            ["document_versions.version_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_edit_drafts_job_base_version_active",
        "edit_drafts",
        ["job_id", "base_version_id"],
        unique=True,
        postgresql_where=sa.text("consumed_at IS NULL"),
    )


def _create_review_operation_batches_table() -> None:
    op.create_table(
        "review_operation_batches",
        sa.Column("operation_batch_id", UUIDType, primary_key=True, nullable=False),
        sa.Column("job_id", UUIDType, nullable=False),
        sa.Column("version_id", UUIDType, nullable=False),
        sa.Column("operation_type", sa.String(length=32), nullable=False),
        sa.Column("affected_count", sa.Integer(), nullable=False),
        sa.Column("undoes_batch_id", UUIDType, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.job_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["document_versions.version_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["undoes_batch_id"],
            ["review_operation_batches.operation_batch_id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_review_operation_batches_job_version_created_at",
        "review_operation_batches",
        ["job_id", "version_id", "created_at", "operation_batch_id"],
        unique=False,
    )


def _create_documents_new_table() -> None:
    op.create_table(
        "documents_new",
        sa.Column("version_id", UUIDType, primary_key=True, nullable=False),
        sa.Column("job_id", UUIDType, nullable=False),
        sa.Column("document_id", UUIDType, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("file_type", sa.String(length=16), nullable=False),
        sa.Column("source_name", sa.String(length=255), nullable=False),
        sa.Column("metadata_json", JSONBType, nullable=False),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["document_versions.version_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.job_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_documents_job_id", "documents_new", ["job_id"], unique=False)


def _create_document_blocks_new_table() -> None:
    op.create_table(
        "document_blocks_new",
        sa.Column("version_id", UUIDType, primary_key=True, nullable=False),
        sa.Column("block_id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("job_id", UUIDType, nullable=False),
        sa.Column("block_order", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("paragraph_index", sa.Integer(), nullable=True),
        sa.Column("parent_id", sa.String(length=64), nullable=True),
        sa.Column("style_json", JSONBType, nullable=False),
        sa.Column("source_locator_json", JSONBType, nullable=False),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["documents_new.version_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.job_id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_document_blocks_version_order",
        "document_blocks_new",
        ["version_id", "block_order"],
        unique=True,
    )


def _create_issues_new_table() -> None:
    op.create_table(
        "issues_new",
        sa.Column("issue_id", UUIDType, primary_key=True, nullable=False),
        sa.Column("version_id", UUIDType, nullable=False),
        sa.Column("job_id", UUIDType, nullable=False),
        sa.Column("document_id", UUIDType, nullable=False),
        sa.Column("document_version", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("rule_id", sa.String(length=128), nullable=False),
        sa.Column("block_id", sa.String(length=64), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("original", sa.Text(), nullable=False),
        sa.Column("suggestion", sa.Text(), nullable=True),
        sa.Column("alternatives_json", JSONBType, nullable=False),
        sa.Column("issue_type", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_version", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("auto_fixable", sa.Boolean(), nullable=False),
        sa.Column("context", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["document_versions.version_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.job_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["version_id", "block_id"],
            ["document_blocks_new.version_id", "document_blocks_new.block_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_issues_version_category", "issues_new", ["version_id", "category"])
    op.create_index("ix_issues_version_severity", "issues_new", ["version_id", "severity"])
    op.create_index(
        "ix_issues_version_block_start",
        "issues_new",
        ["version_id", "block_id", "start_offset"],
    )


def _create_checker_failures_new_table() -> None:
    op.create_table(
        "checker_failures_new",
        sa.Column("version_id", UUIDType, primary_key=True, nullable=False),
        sa.Column("job_id", UUIDType, nullable=False),
        sa.Column("category", sa.String(length=32), primary_key=True, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["document_versions.version_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.job_id"], ondelete="CASCADE"),
    )


def _create_issue_suggestions_new_table() -> None:
    op.create_table(
        "issue_suggestions_new",
        sa.Column("suggestion_id", UUIDType, primary_key=True, nullable=False),
        sa.Column("issue_id", UUIDType, nullable=False),
        sa.Column("version_id", UUIDType, nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("preferred", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["issue_id"], ["issues_new.issue_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["document_versions.version_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_issue_suggestions_issue_rank",
        "issue_suggestions_new",
        ["issue_id", "rank"],
        unique=True,
    )
    op.create_index(
        "ix_issue_suggestions_issue_preferred",
        "issue_suggestions_new",
        ["issue_id"],
        unique=True,
        postgresql_where=sa.text("preferred"),
    )


def _create_review_operation_items_table() -> None:
    op.create_table(
        "review_operation_items",
        sa.Column("operation_batch_id", UUIDType, primary_key=True, nullable=False),
        sa.Column("sequence", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("issue_id", UUIDType, nullable=False),
        sa.Column("before_json", JSONBType, nullable=True),
        sa.Column("after_json", JSONBType, nullable=True),
        sa.CheckConstraint(
            "before_json IS NOT NULL OR after_json IS NOT NULL",
            name="ck_review_operation_items_snapshot",
        ),
        sa.ForeignKeyConstraint(
            ["operation_batch_id"],
            ["review_operation_batches.operation_batch_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["issue_id"], ["issues_new.issue_id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_review_operation_items_batch_sequence",
        "review_operation_items",
        ["operation_batch_id", "sequence"],
        unique=True,
    )


def _create_issue_decisions_new_table() -> None:
    op.create_table(
        "issue_decisions_new",
        sa.Column("issue_id", UUIDType, primary_key=True, nullable=False),
        sa.Column("version_id", UUIDType, nullable=False),
        sa.Column("job_id", UUIDType, nullable=False),
        sa.Column("issue_version", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("replacement", sa.Text(), nullable=True),
        sa.Column("final_replacement", sa.Text(), nullable=True),
        sa.Column("suggestion_id", UUIDType, nullable=True),
        sa.Column("operation_batch_id", UUIDType, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
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
            name="ck_issue_decisions_action_replacement_new",
        ),
        sa.ForeignKeyConstraint(["issue_id"], ["issues_new.issue_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["document_versions.version_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.job_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["suggestion_id"],
            ["issue_suggestions_new.suggestion_id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["operation_batch_id"],
            ["review_operation_batches.operation_batch_id"],
            ondelete="SET NULL",
        ),
    )


def _create_documents_legacy_table() -> None:
    op.create_table(
        "documents_legacy",
        sa.Column("job_id", UUIDType, primary_key=True, nullable=False),
        sa.Column("document_id", UUIDType, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("file_type", sa.String(length=16), nullable=False),
        sa.Column("source_name", sa.String(length=255), nullable=False),
        sa.Column("metadata_json", JSONBType, nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.job_id"], ondelete="CASCADE"),
    )


def _create_document_blocks_legacy_table() -> None:
    op.create_table(
        "document_blocks_legacy",
        sa.Column("job_id", UUIDType, primary_key=True, nullable=False),
        sa.Column("block_id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("block_order", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("paragraph_index", sa.Integer(), nullable=True),
        sa.Column("parent_id", sa.String(length=64), nullable=True),
        sa.Column("style_json", JSONBType, nullable=False),
        sa.Column("source_locator_json", JSONBType, nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["documents_legacy.job_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_document_blocks_job_order",
        "document_blocks_legacy",
        ["job_id", "block_order"],
        unique=True,
    )


def _create_issues_legacy_table() -> None:
    op.create_table(
        "issues_legacy",
        sa.Column("issue_id", UUIDType, primary_key=True, nullable=False),
        sa.Column("job_id", UUIDType, nullable=False),
        sa.Column("document_id", UUIDType, nullable=False),
        sa.Column("document_version", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("rule_id", sa.String(length=128), nullable=False),
        sa.Column("block_id", sa.String(length=64), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("original", sa.Text(), nullable=False),
        sa.Column("suggestion", sa.Text(), nullable=True),
        sa.Column("alternatives_json", JSONBType, nullable=False),
        sa.Column("issue_type", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_version", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("auto_fixable", sa.Boolean(), nullable=False),
        sa.Column("context", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["documents_legacy.job_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["job_id", "block_id"],
            ["document_blocks_legacy.job_id", "document_blocks_legacy.block_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_issues_job_category", "issues_legacy", ["job_id", "category"])
    op.create_index("ix_issues_job_severity", "issues_legacy", ["job_id", "severity"])
    op.create_index(
        "ix_issues_job_block_start",
        "issues_legacy",
        ["job_id", "block_id", "start_offset"],
    )


def _create_checker_failures_legacy_table() -> None:
    op.create_table(
        "checker_failures_legacy",
        sa.Column("job_id", UUIDType, primary_key=True, nullable=False),
        sa.Column("category", sa.String(length=32), primary_key=True, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["documents_legacy.job_id"], ondelete="CASCADE"),
    )


def _create_issue_decisions_legacy_table() -> None:
    op.create_table(
        "issue_decisions_legacy",
        sa.Column("issue_id", UUIDType, primary_key=True, nullable=False),
        sa.Column("job_id", UUIDType, nullable=False),
        sa.Column("issue_version", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("replacement", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            """
            (
                action = 'custom'
                AND replacement IS NOT NULL
                AND replacement ~ '[^[:space:]]'
            )
            OR (
                action IN ('accepted', 'ignored')
                AND replacement IS NULL
            )
            """,
            name="ck_issue_decisions_action_replacement",
        ),
        sa.ForeignKeyConstraint(["issue_id"], ["issues_legacy.issue_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.job_id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_issue_decisions_job_action",
        "issue_decisions_legacy",
        ["job_id", "action"],
        unique=False,
    )
