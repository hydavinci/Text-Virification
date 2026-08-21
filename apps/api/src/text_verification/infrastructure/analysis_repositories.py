from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import Select, and_, delete, func, literal, or_, select
from sqlalchemy.orm import Session

from text_verification.checkers.models import CheckCategory, CheckerFailure
from text_verification.domain.documents import DocumentModel, FileType, TextBlock
from text_verification.domain.issues import (
    DecisionAction,
    Issue,
    IssueDecisionSummary,
    IssueSeverity,
)
from text_verification.domain.revisions import (
    DocumentVersionStatus,
    ImmutableDocumentVersionError,
)
from text_verification.infrastructure.orm import (
    CheckerFailureRow,
    DocumentBlockRow,
    DocumentRow,
    DocumentVersionRow,
    IssueDecisionRow,
    IssueRow,
    JobRow,
)

UNREVIEWED_DECISION = "unreviewed"
SUMMARY_DECISION_STATES = ("accepted", "ignored", UNREVIEWED_DECISION)
SUPPORTED_DECISIONS = set(SUMMARY_DECISION_STATES)
BlockKind = Literal["paragraph", "heading", "table_cell", "header", "footer"]


@dataclass(frozen=True)
class IssueQuery:
    category: CheckCategory | None = None
    severity: IssueSeverity | None = None
    decision: str | None = None
    search: str | None = None
    cursor: str | None = None
    limit: int = 50

    def __post_init__(self) -> None:
        if self.category is not None and not isinstance(self.category, CheckCategory):
            object.__setattr__(self, "category", CheckCategory(self.category))
        if self.severity is not None and not isinstance(self.severity, IssueSeverity):
            object.__setattr__(self, "severity", IssueSeverity(self.severity))
        if self.decision is not None and self.decision not in SUPPORTED_DECISIONS:
            raise ValueError(f"Unsupported decision filter: {self.decision}")
        if self.limit <= 0:
            raise ValueError("limit must be positive")
        if self.search is not None:
            normalized_search = self.search.strip()
            object.__setattr__(self, "search", normalized_search or None)


@dataclass(frozen=True)
class IssuePage:
    items: list[Issue]
    total: int
    next_cursor: str | None


@dataclass(frozen=True)
class DocumentQuery:
    cursor: str | None = None
    limit: int = 100

    def __post_init__(self) -> None:
        if self.limit <= 0:
            raise ValueError("limit must be positive")


@dataclass(frozen=True)
class DocumentPage:
    document_id: UUID
    file_type: FileType
    source_name: str
    version: int
    metadata: dict[str, object]
    blocks: list[TextBlock]
    total_blocks: int
    next_cursor: str | None


@dataclass(frozen=True)
class IssueSummary:
    total: int
    by_category: dict[CheckCategory, int]
    by_severity: dict[IssueSeverity, int]
    by_decision: dict[str, int]


@dataclass(frozen=True)
class _IssueCursor:
    block_order: int
    start_offset: int
    issue_id: UUID


@dataclass(frozen=True)
class _DocumentCursor:
    block_order: int


class InvalidCursorError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class AnalysisRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def replace_analysis(
        self,
        job_id: UUID,
        document: DocumentModel,
        issues: list[Issue],
        failures: dict[CheckCategory, CheckerFailure],
    ) -> None:
        self._validate_issues(document, issues)
        from text_verification.infrastructure.revision_repository import RevisionRepository

        revisions = RevisionRepository(self._session)
        current_version_id = self._current_version_id(job_id)
        version = revisions.create_queued_version(
            job_id,
            parent_version_id=current_version_id,
            reason="upload" if current_version_id is None else "edited",
            idempotency_key=None,
        )
        revisions.mark_analyzing(version.version_id)
        revisions.complete_analysis(version.version_id, document, issues, failures)

    def persist_version_analysis(
        self,
        version_id: UUID,
        document: DocumentModel,
        issues: list[Issue],
        failures: dict[CheckCategory, CheckerFailure],
    ) -> None:
        version = self._lock_version(version_id)
        status = DocumentVersionStatus(version.status)
        if status in {DocumentVersionStatus.SUCCEEDED, DocumentVersionStatus.FAILED}:
            raise ImmutableDocumentVersionError(version_id, status)

        job_id = version.job_id
        self._validate_issues(document, issues)
        self._session.execute(
            delete(CheckerFailureRow)
            .where(CheckerFailureRow.version_id == version_id)
            .execution_options(synchronize_session="fetch")
        )
        self._session.execute(
            delete(IssueRow)
            .where(IssueRow.version_id == version_id)
            .execution_options(synchronize_session="fetch")
        )
        self._session.execute(
            delete(DocumentBlockRow)
            .where(DocumentBlockRow.version_id == version_id)
            .execution_options(synchronize_session="fetch")
        )
        self._session.execute(
            delete(DocumentRow)
            .where(DocumentRow.version_id == version_id)
            .execution_options(synchronize_session="fetch")
        )

        document_row = DocumentRow(
            version_id=version_id,
            job_id=job_id,
            document_id=document.document_id,
            version=document.version,
            file_type=document.file_type.value,
            source_name=document.source_name,
            metadata_json=document.metadata,
            blocks=[
                DocumentBlockRow(
                    version_id=version_id,
                    job_id=job_id,
                    block_id=block.block_id,
                    block_order=block_order,
                    kind=block.kind,
                    text=block.text,
                    page=block.page,
                    paragraph_index=block.paragraph_index,
                    parent_id=block.parent_id,
                    style_json=block.style,
                    source_locator_json=block.source_locator,
                )
                for block_order, block in enumerate(document.blocks)
            ],
        )
        self._session.add(document_row)
        self._session.flush()

        for issue in issues:
            self._session.add(
                IssueRow(
                    issue_id=issue.issue_id,
                    version_id=version_id,
                    job_id=job_id,
                    document_id=issue.document_id,
                    document_version=document.version,
                    category=issue.layer,
                    severity=issue.severity.value,
                    rule_id=issue.rule_id,
                    block_id=issue.block_id,
                    page=issue.page,
                    start_offset=issue.start,
                    end_offset=issue.end,
                    original=issue.original,
                    suggestion=issue.suggestion,
                    alternatives_json=issue.alternatives,
                    issue_type=issue.type,
                    message=issue.message,
                    source=issue.source,
                    source_version=issue.source_version,
                    confidence=issue.confidence,
                    auto_fixable=issue.auto_fixable,
                    context=issue.context,
                )
            )

        for category, failure in failures.items():
            self._session.add(
                CheckerFailureRow(
                    version_id=version_id,
                    job_id=job_id,
                    category=category.value,
                    code=failure.code,
                    message=failure.message,
                )
            )
        self._session.flush()

    def get_document(self, job_id: UUID, version_id: UUID | None = None) -> DocumentModel | None:
        row = self._find_document_row(job_id, version_id=version_id)
        if row is None:
            return None

        return DocumentModel(
            document_id=row.document_id,
            file_type=FileType(row.file_type),
            source_name=row.source_name,
            version=row.version,
            blocks=[
                TextBlock(
                    block_id=block.block_id,
                    kind=cast(BlockKind, block.kind),
                    text=block.text,
                    page=block.page,
                    paragraph_index=block.paragraph_index,
                    parent_id=block.parent_id,
                    style=block.style_json,
                    source_locator=block.source_locator_json,
                )
                for block in row.blocks
            ],
            metadata=row.metadata_json,
        )

    def has_analysis(self, job_id: UUID, version_id: UUID | None = None) -> bool:
        return self._find_document_row(job_id, version_id=version_id) is not None

    def list_document_blocks(
        self,
        job_id: UUID,
        query: DocumentQuery,
        version_id: UUID | None = None,
    ) -> DocumentPage | None:
        row = self._find_document_row(job_id, version_id=version_id)
        if row is None:
            return None

        total_blocks = int(
            self._session.scalar(
                select(func.count())
                .select_from(DocumentBlockRow)
                .where(DocumentBlockRow.version_id == row.version_id)
            )
            or 0
        )

        cursor = _decode_document_cursor(query.cursor) if query.cursor is not None else None
        statement = (
            select(DocumentBlockRow)
            .where(DocumentBlockRow.version_id == row.version_id)
            .order_by(DocumentBlockRow.block_order)
        )
        if cursor is not None:
            statement = statement.where(DocumentBlockRow.block_order > cursor.block_order)

        block_rows = self._session.scalars(statement.limit(query.limit + 1)).all()
        visible_rows = block_rows[: query.limit]
        next_cursor = None
        if len(block_rows) > query.limit:
            next_cursor = _encode_document_cursor(
                _DocumentCursor(block_order=visible_rows[-1].block_order)
            )

        return DocumentPage(
            document_id=row.document_id,
            file_type=FileType(row.file_type),
            source_name=row.source_name,
            version=row.version,
            metadata=row.metadata_json,
            blocks=[_to_text_block(block_row) for block_row in visible_rows],
            total_blocks=total_blocks,
            next_cursor=next_cursor,
        )

    def list_issues(
        self,
        job_id: UUID,
        query: IssueQuery,
        version_id: UUID | None = None,
    ) -> IssuePage:
        resolved_version_id = self._resolve_version_id(job_id, version_id)
        if resolved_version_id is None:
            return IssuePage(items=[], total=0, next_cursor=None)

        filtered_issue_ids = self._filtered_issue_ids_query(resolved_version_id, query)
        total = int(
            self._session.scalar(
                select(func.count())
                .select_from(filtered_issue_ids.subquery())
            )
            or 0
        )

        cursor = _decode_issue_cursor(query.cursor) if query.cursor is not None else None
        statement = (
            select(
                IssueRow,
                DocumentBlockRow.block_order,
                IssueDecisionRow,
            )
            .join(
                DocumentBlockRow,
                and_(
                    DocumentBlockRow.version_id == IssueRow.version_id,
                    DocumentBlockRow.block_id == IssueRow.block_id,
                ),
            )
            .outerjoin(IssueDecisionRow, IssueDecisionRow.issue_id == IssueRow.issue_id)
            .where(IssueRow.version_id == resolved_version_id)
        )

        if query.category is not None:
            statement = statement.where(IssueRow.category == query.category.value)
        if query.severity is not None:
            statement = statement.where(IssueRow.severity == query.severity.value)
        if query.decision == UNREVIEWED_DECISION:
            statement = statement.where(IssueDecisionRow.issue_id.is_(None))
        elif query.decision is not None:
            statement = statement.where(IssueDecisionRow.action == query.decision)
        if query.search is not None:
            statement = statement.where(IssueRow.original.ilike(f"%{query.search}%"))
        if cursor is not None:
            statement = statement.where(
                or_(
                    DocumentBlockRow.block_order > cursor.block_order,
                    and_(
                        DocumentBlockRow.block_order == cursor.block_order,
                        IssueRow.start_offset > cursor.start_offset,
                    ),
                    and_(
                        DocumentBlockRow.block_order == cursor.block_order,
                        IssueRow.start_offset == cursor.start_offset,
                        IssueRow.issue_id > cursor.issue_id,
                    ),
                )
            )

        statement = statement.order_by(
            DocumentBlockRow.block_order,
            IssueRow.start_offset,
            IssueRow.issue_id,
        ).limit(query.limit + 1)

        result_rows = self._session.execute(statement).all()
        visible_rows = result_rows[: query.limit]
        items = [
            _to_issue(issue_row=issue_row, decision_row=decision_row)
            for issue_row, _block_order, decision_row in visible_rows
        ]
        next_cursor = None
        if len(result_rows) > query.limit:
            last_issue_row, block_order, _decision_row = visible_rows[-1]
            next_cursor = _encode_issue_cursor(
                _IssueCursor(
                    block_order=block_order,
                    start_offset=last_issue_row.start_offset,
                    issue_id=last_issue_row.issue_id,
                )
            )

        return IssuePage(items=items, total=total, next_cursor=next_cursor)

    def list_all_issues(self, job_id: UUID, version_id: UUID | None = None) -> list[Issue]:
        resolved_version_id = self._resolve_version_id(job_id, version_id)
        if resolved_version_id is None:
            return []
        rows = self._session.execute(
            select(
                IssueRow,
                DocumentBlockRow.block_order,
                IssueDecisionRow,
            )
            .join(
                DocumentBlockRow,
                and_(
                    DocumentBlockRow.version_id == IssueRow.version_id,
                    DocumentBlockRow.block_id == IssueRow.block_id,
                ),
            )
            .outerjoin(IssueDecisionRow, IssueDecisionRow.issue_id == IssueRow.issue_id)
            .where(IssueRow.version_id == resolved_version_id)
            .order_by(
                DocumentBlockRow.block_order,
                IssueRow.start_offset,
                IssueRow.issue_id,
            )
        ).all()
        return [
            _to_issue(issue_row=issue_row, decision_row=decision_row)
            for issue_row, _block_order, decision_row in rows
        ]

    def get_checker_failures(
        self,
        job_id: UUID,
        version_id: UUID | None = None,
    ) -> dict[CheckCategory, CheckerFailure]:
        resolved_version_id = self._resolve_version_id(job_id, version_id)
        if resolved_version_id is None:
            return {}
        rows = self._session.scalars(
            select(CheckerFailureRow)
            .where(CheckerFailureRow.version_id == resolved_version_id)
            .order_by(CheckerFailureRow.category)
        ).all()
        return {
            CheckCategory(row.category): CheckerFailure(code=row.code, message=row.message)
            for row in rows
        }

    def summarize_issues(
        self,
        job_id: UUID,
        version_id: UUID | None = None,
    ) -> IssueSummary:
        resolved_version_id = self._resolve_version_id(job_id, version_id)
        if resolved_version_id is None:
            return IssueSummary(total=0, by_category={}, by_severity={}, by_decision={})
        category_rows = self._session.execute(
            select(IssueRow.category, func.count())
            .where(IssueRow.version_id == resolved_version_id)
            .group_by(IssueRow.category)
        ).all()
        severity_rows = self._session.execute(
            select(IssueRow.severity, func.count())
            .where(IssueRow.version_id == resolved_version_id)
            .group_by(IssueRow.severity)
        ).all()
        decision_group = func.coalesce(IssueDecisionRow.action, literal(UNREVIEWED_DECISION))
        decision_rows = self._session.execute(
            select(decision_group, func.count())
            .select_from(IssueRow)
            .outerjoin(IssueDecisionRow, IssueDecisionRow.issue_id == IssueRow.issue_id)
            .where(IssueRow.version_id == resolved_version_id)
            .group_by(decision_group)
        ).all()
        by_category = {
            CheckCategory(category): int(count) for category, count in category_rows
        }
        by_severity = {
            IssueSeverity(severity): int(count) for severity, count in severity_rows
        }
        by_decision = {str(decision): int(count) for decision, count in decision_rows}
        return IssueSummary(
            total=sum(by_category.values()),
            by_category=by_category,
            by_severity=by_severity,
            by_decision=by_decision,
        )

    def _filtered_issue_ids_query(
        self,
        version_id: UUID,
        query: IssueQuery,
    ) -> Select[tuple[UUID]]:
        statement = select(IssueRow.issue_id).where(IssueRow.version_id == version_id)
        if query.decision is not None:
            statement = statement.outerjoin(
                IssueDecisionRow,
                IssueDecisionRow.issue_id == IssueRow.issue_id,
            )
        if query.category is not None:
            statement = statement.where(IssueRow.category == query.category.value)
        if query.severity is not None:
            statement = statement.where(IssueRow.severity == query.severity.value)
        if query.decision == UNREVIEWED_DECISION:
            statement = statement.where(IssueDecisionRow.issue_id.is_(None))
        elif query.decision is not None:
            statement = statement.where(IssueDecisionRow.action == query.decision)
        if query.search is not None:
            statement = statement.where(IssueRow.original.ilike(f"%{query.search}%"))
        return statement

    def _validate_issues(self, document: DocumentModel, issues: list[Issue]) -> None:
        block_pages = {block.block_id: block.page for block in document.blocks}
        for issue in issues:
            if issue.document_id != document.document_id:
                raise ValueError("issue document_id must match the persisted document")
            block_page = block_pages.get(issue.block_id)
            if issue.block_id in block_pages and issue.page != block_page:
                raise ValueError("issue page must match the referenced document block page")

    def _current_version_id(self, job_id: UUID) -> UUID | None:
        version_id = self._session.scalar(
            select(JobRow.active_version_id).where(JobRow.job_id == job_id)
        )
        if version_id is not None:
            return version_id
        return self._session.scalar(
            select(DocumentRow.version_id)
            .where(DocumentRow.job_id == job_id)
            .order_by(DocumentRow.version.desc())
            .limit(1)
        )

    def _resolve_version_id(self, job_id: UUID, version_id: UUID | None = None) -> UUID | None:
        if version_id is not None:
            return self._session.scalar(
                select(DocumentVersionRow.version_id).where(
                    DocumentVersionRow.job_id == job_id,
                    DocumentVersionRow.version_id == version_id,
                )
            )
        return self._current_version_id(job_id)

    def _find_document_row(
        self,
        job_id: UUID,
        *,
        version_id: UUID | None = None,
        lock: bool = False,
    ) -> DocumentRow | None:
        resolved_version_id = self._resolve_version_id(job_id, version_id)
        if resolved_version_id is None:
            return None
        statement = select(DocumentRow).where(
            DocumentRow.job_id == job_id,
            DocumentRow.version_id == resolved_version_id,
        )
        if lock:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        return self._session.execute(statement).scalar_one_or_none()

    def _lock_version(self, version_id: UUID) -> DocumentVersionRow:
        version = self._session.execute(
            select(DocumentVersionRow)
            .where(DocumentVersionRow.version_id == version_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if version is None:
            raise LookupError(f"Document version {version_id} does not exist.")
        return version


def _to_issue(*, issue_row: IssueRow, decision_row: IssueDecisionRow | None) -> Issue:
    return Issue(
        issue_id=issue_row.issue_id,
        document_id=issue_row.document_id,
        document_version=issue_row.document_version,
        block_id=issue_row.block_id,
        page=issue_row.page,
        start=issue_row.start_offset,
        end=issue_row.end_offset,
        original=issue_row.original,
        suggestion=issue_row.suggestion,
        alternatives=issue_row.alternatives_json,
        type=issue_row.issue_type,
        severity=IssueSeverity(issue_row.severity),
        layer=issue_row.category,
        message=issue_row.message,
        rule_id=issue_row.rule_id,
        source=issue_row.source,
        source_version=issue_row.source_version,
        confidence=issue_row.confidence,
        auto_fixable=issue_row.auto_fixable,
        context=issue_row.context,
        decision=_to_issue_decision_summary(decision_row),
    )


def _to_issue_decision_summary(row: IssueDecisionRow | None) -> IssueDecisionSummary | None:
    if row is None:
        return None
    return IssueDecisionSummary(
        issue_version=row.issue_version,
        revision=row.revision,
        action=DecisionAction(row.action),
        replacement=row.final_replacement or row.replacement,
        suggestion_id=row.suggestion_id,
        updated_at=row.updated_at,
    )


def _to_text_block(block_row: DocumentBlockRow) -> TextBlock:
    return TextBlock(
        block_id=block_row.block_id,
        kind=cast(BlockKind, block_row.kind),
        text=block_row.text,
        page=block_row.page,
        paragraph_index=block_row.paragraph_index,
        parent_id=block_row.parent_id,
        style=block_row.style_json,
        source_locator=block_row.source_locator_json,
    )


def _encode_issue_cursor(cursor: _IssueCursor) -> str:
    payload = json.dumps(
        {
            "block_order": cursor.block_order,
            "start_offset": cursor.start_offset,
            "issue_id": str(cursor.issue_id),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_issue_cursor(value: str) -> _IssueCursor:
    data = _decode_cursor_payload(
        value,
        code="invalid_issue_cursor",
        message="问题分页游标无效，请刷新后重试。",
    )
    return _IssueCursor(
        block_order=_require_int_field(data, "block_order", code="invalid_issue_cursor"),
        start_offset=_require_int_field(data, "start_offset", code="invalid_issue_cursor"),
        issue_id=_require_uuid_field(data, "issue_id", code="invalid_issue_cursor"),
    )


def _encode_document_cursor(cursor: _DocumentCursor) -> str:
    payload = json.dumps({"block_order": cursor.block_order}, separators=(",", ":")).encode(
        "utf-8"
    )
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_document_cursor(value: str) -> _DocumentCursor:
    data = _decode_cursor_payload(
        value,
        code="invalid_document_cursor",
        message="文档分页游标无效，请刷新后重试。",
    )
    return _DocumentCursor(
        block_order=_require_int_field(data, "block_order", code="invalid_document_cursor")
    )


def _decode_cursor_payload(value: str, *, code: str, message: str) -> dict[str, object]:
    padded_value = value + "=" * (-len(value) % 4)
    try:
        decoded = base64.b64decode(padded_value.encode("ascii"), altchars=b"-_", validate=True)
        data = json.loads(decoded.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise InvalidCursorError(code, message) from error
    if not isinstance(data, dict):
        raise InvalidCursorError(code, message)
    return data


def _require_int_field(data: dict[str, object], field: str, *, code: str) -> int:
    raw_value = data.get(field)
    if not isinstance(raw_value, int | str):
        raise InvalidCursorError(code, _cursor_message(code))
    try:
        return int(raw_value)
    except ValueError as error:
        raise InvalidCursorError(code, _cursor_message(code)) from error


def _require_uuid_field(data: dict[str, object], field: str, *, code: str) -> UUID:
    try:
        return UUID(str(data[field]))
    except (KeyError, TypeError, ValueError) as error:
        raise InvalidCursorError(code, _cursor_message(code)) from error


def _cursor_message(code: str) -> str:
    return (
        "文档分页游标无效，请刷新后重试。"
        if code == "invalid_document_cursor"
        else "问题分页游标无效，请刷新后重试。"
    )
