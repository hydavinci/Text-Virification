from __future__ import annotations

import base64
import json
from dataclasses import dataclass
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
class _IssueCursor:
    block_order: int
    start_offset: int
    issue_id: UUID


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
                    kind=block.kind,
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

        cursor = _decode_cursor(query.cursor) if query.cursor is not None else None
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
            next_cursor = _encode_cursor(
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


def _encode_cursor(cursor: _IssueCursor) -> str:
    payload = json.dumps(
        {
            "block_order": cursor.block_order,
            "start_offset": cursor.start_offset,
            "issue_id": str(cursor.issue_id),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> _IssueCursor:
    padded_value = value + "=" * (-len(value) % 4)
    data = json.loads(base64.urlsafe_b64decode(padded_value).decode("utf-8"))
    return _IssueCursor(
        block_order=int(data["block_order"]),
        start_offset=int(data["start_offset"]),
        issue_id=UUID(str(data["issue_id"])),
    )
