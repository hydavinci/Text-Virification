from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import Select, and_, delete, func, or_, select
from sqlalchemy.orm import Session

from text_verification.checkers.models import CheckCategory, CheckerFailure
from text_verification.domain.documents import DocumentModel, FileType, TextBlock
from text_verification.domain.issues import Issue, IssueSeverity
from text_verification.infrastructure.orm import (
    CheckerFailureRow,
    DocumentBlockRow,
    DocumentRow,
    IssueRow,
    JobRow,
)

PENDING_DECISION = "pending"
SUPPORTED_DECISIONS = {"accepted", "custom", "ignored", PENDING_DECISION}
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
        self._lock_job(job_id)
        self._validate_issues(document, issues)
        self._session.execute(
            delete(CheckerFailureRow)
            .where(CheckerFailureRow.job_id == job_id)
            .execution_options(synchronize_session="fetch")
        )
        self._session.execute(
            delete(IssueRow)
            .where(IssueRow.job_id == job_id)
            .execution_options(synchronize_session="fetch")
        )
        self._session.execute(
            delete(DocumentBlockRow)
            .where(DocumentBlockRow.job_id == job_id)
            .execution_options(synchronize_session="fetch")
        )
        self._session.execute(
            delete(DocumentRow)
            .where(DocumentRow.job_id == job_id)
            .execution_options(synchronize_session="fetch")
        )

        document_row = DocumentRow(
            job_id=job_id,
            document_id=document.document_id,
            version=document.version,
            file_type=document.file_type.value,
            source_name=document.source_name,
            metadata_json=document.metadata,
            blocks=[
                DocumentBlockRow(
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
                    job_id=job_id,
                    category=category.value,
                    code=failure.code,
                    message=failure.message,
                )
            )

    def get_document(self, job_id: UUID) -> DocumentModel | None:
        row = self._session.get(DocumentRow, job_id)
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

    def has_analysis(self, job_id: UUID) -> bool:
        return self._session.get(DocumentRow, job_id) is not None

    def list_document_blocks(self, job_id: UUID, query: DocumentQuery) -> DocumentPage | None:
        row = self._session.get(DocumentRow, job_id)
        if row is None:
            return None

        total_blocks = int(
            self._session.scalar(
                select(func.count())
                .select_from(DocumentBlockRow)
                .where(DocumentBlockRow.job_id == job_id)
            )
            or 0
        )

        cursor = _decode_document_cursor(query.cursor) if query.cursor is not None else None
        statement = (
            select(DocumentBlockRow)
            .where(DocumentBlockRow.job_id == job_id)
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

    def list_issues(self, job_id: UUID, query: IssueQuery) -> IssuePage:
        if query.decision not in (None, PENDING_DECISION):
            return IssuePage(items=[], total=0, next_cursor=None)

        filtered_issue_ids = self._filtered_issue_ids_query(job_id, query)
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
            )
            .join(
                DocumentBlockRow,
                and_(
                    DocumentBlockRow.job_id == IssueRow.job_id,
                    DocumentBlockRow.block_id == IssueRow.block_id,
                ),
            )
            .where(IssueRow.job_id == job_id)
        )

        if query.category is not None:
            statement = statement.where(IssueRow.category == query.category.value)
        if query.severity is not None:
            statement = statement.where(IssueRow.severity == query.severity.value)
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
            _to_issue(issue_row=issue_row)
            for issue_row, _block_order in visible_rows
        ]
        next_cursor = None
        if len(result_rows) > query.limit:
            last_issue_row, block_order = visible_rows[-1]
            next_cursor = _encode_issue_cursor(
                _IssueCursor(
                    block_order=block_order,
                    start_offset=last_issue_row.start_offset,
                    issue_id=last_issue_row.issue_id,
                )
            )

        return IssuePage(items=items, total=total, next_cursor=next_cursor)

    def get_checker_failures(self, job_id: UUID) -> dict[CheckCategory, CheckerFailure]:
        rows = self._session.scalars(
            select(CheckerFailureRow)
            .where(CheckerFailureRow.job_id == job_id)
            .order_by(CheckerFailureRow.category)
        ).all()
        return {
            CheckCategory(row.category): CheckerFailure(code=row.code, message=row.message)
            for row in rows
        }

    def summarize_issues(self, job_id: UUID) -> IssueSummary:
        category_rows = self._session.execute(
            select(IssueRow.category, func.count())
            .where(IssueRow.job_id == job_id)
            .group_by(IssueRow.category)
        ).all()
        severity_rows = self._session.execute(
            select(IssueRow.severity, func.count())
            .where(IssueRow.job_id == job_id)
            .group_by(IssueRow.severity)
        ).all()
        by_category = {
            CheckCategory(category): int(count) for category, count in category_rows
        }
        by_severity = {
            IssueSeverity(severity): int(count) for severity, count in severity_rows
        }
        return IssueSummary(
            total=sum(by_category.values()),
            by_category=by_category,
            by_severity=by_severity,
        )

    def _filtered_issue_ids_query(self, job_id: UUID, query: IssueQuery) -> Select[tuple[UUID]]:
        statement = select(IssueRow.issue_id).where(IssueRow.job_id == job_id)
        if query.category is not None:
            statement = statement.where(IssueRow.category == query.category.value)
        if query.severity is not None:
            statement = statement.where(IssueRow.severity == query.severity.value)
        if query.search is not None:
            statement = statement.where(IssueRow.original.ilike(f"%{query.search}%"))
        return statement

    def _lock_job(self, job_id: UUID) -> JobRow:
        row = self._session.execute(
            select(JobRow)
            .where(JobRow.job_id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if row is None:
            raise LookupError(f"Job {job_id} does not exist.")
        return row

    def _validate_issues(self, document: DocumentModel, issues: list[Issue]) -> None:
        block_pages = {block.block_id: block.page for block in document.blocks}
        for issue in issues:
            if issue.document_id != document.document_id:
                raise ValueError("issue document_id must match the persisted document")
            block_page = block_pages.get(issue.block_id)
            if issue.block_id in block_pages and issue.page != block_page:
                raise ValueError("issue page must match the referenced document block page")


def _to_issue(*, issue_row: IssueRow) -> Issue:
    return Issue(
        issue_id=issue_row.issue_id,
        document_id=issue_row.document_id,
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
