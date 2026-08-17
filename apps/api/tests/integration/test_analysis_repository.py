from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from text_verification.checkers.models import CheckCategory, CheckerFailure
from text_verification.domain.documents import DocumentModel, FileType, TextBlock
from text_verification.domain.issues import Issue, IssueSeverity
from text_verification.infrastructure.analysis_repositories import (
    AnalysisRepository,
    IssueQuery,
)
from text_verification.infrastructure.orm import IssueRow
from text_verification.infrastructure.repositories import JobRepository


def test_repository_round_trips_document_issue_and_failures_exactly(db_session: Session) -> None:
    repository = AnalysisRepository(db_session)
    job_id = seed_job(db_session)
    document = build_document([("绝对领先", 7)])
    issue = build_issue(
        document,
        block_id="p-000001",
        original="绝对领先",
        suggestion="领先",
        start=0,
        end=4,
        page=7,
        issue_type="regex",
    )
    failures = {
        CheckCategory.SECURITY: CheckerFailure(
            code="checker_crashed",
            message="安全检查器暂时不可用。",
        )
    }

    repository.replace_analysis(job_id, document, [issue], failures)
    db_session.commit()

    stored = repository.get_document(job_id)
    page = repository.list_issues(job_id, IssueQuery(limit=20))
    persisted_issue = db_session.get(IssueRow, issue.issue_id)

    assert stored == document
    assert page.items == [issue]
    assert page.total == 1
    assert page.next_cursor is None
    assert repository.get_checker_failures(job_id) == failures
    assert persisted_issue is not None
    assert persisted_issue.document_id == issue.document_id
    assert persisted_issue.page == issue.page
    assert persisted_issue.issue_type == issue.type


def test_replace_analysis_is_atomic(db_session: Session) -> None:
    repository = AnalysisRepository(db_session)
    job_id = seed_job(db_session)
    original_document = build_document([("旧", None)])
    repository.replace_analysis(job_id, original_document, [], {})
    db_session.commit()

    with pytest.raises(IntegrityError):
        repository.replace_analysis(
            job_id,
            build_document([("新", None)]),
            [invalid_issue(document_id=original_document.document_id)],
            {},
        )
        db_session.flush()

    db_session.rollback()

    stored = repository.get_document(job_id)
    assert stored is not None
    assert stored.blocks[0].text == "旧"


def test_replace_analysis_rejects_issue_with_mismatched_document_id(db_session: Session) -> None:
    repository = AnalysisRepository(db_session)
    job_id = seed_job(db_session)
    document = build_document([("正文", 3)])
    repository.replace_analysis(job_id, document, [], {})
    db_session.commit()

    with pytest.raises(ValueError, match="document_id"):
        repository.replace_analysis(
            job_id,
            document,
            [
                build_issue(
                    document,
                    block_id="p-000001",
                    original="正文",
                    suggestion="修正",
                    start=0,
                    end=2,
                    page=3,
                    document_id=UUID("00000000-0000-0000-0000-000000000099"),
                )
            ],
            {},
        )

    stored = repository.get_document(job_id)
    assert stored == document


def test_replace_analysis_rejects_issue_with_page_mismatched_to_block(db_session: Session) -> None:
    repository = AnalysisRepository(db_session)
    job_id = seed_job(db_session)
    document = build_document([("正文", 3)])
    repository.replace_analysis(job_id, document, [], {})
    db_session.commit()

    with pytest.raises(ValueError, match="page"):
        repository.replace_analysis(
            job_id,
            document,
            [
                build_issue(
                    document,
                    block_id="p-000001",
                    original="正文",
                    suggestion="修正",
                    start=0,
                    end=2,
                    page=9,
                )
            ],
            {},
        )

    stored = repository.get_document(job_id)
    assert stored == document


def test_list_issues_filters_and_paginates_stably(db_session: Session) -> None:
    repository = AnalysisRepository(db_session)
    job_id = seed_job(db_session)
    document = build_document([("Absolute Alpha", 1), ("Beta absolute", 2)])
    issue_first = build_issue(
        document,
        block_id="p-000001",
        original="Absolute",
        suggestion="Alpha",
        start=0,
        end=8,
        page=1,
        issue_id=UUID("00000000-0000-0000-0000-000000000001"),
        category=CheckCategory.SECURITY,
        severity=IssueSeverity.WARNING,
    )
    issue_second = build_issue(
        document,
        block_id="p-000001",
        original="Alpha",
        suggestion="A",
        start=9,
        end=14,
        page=1,
        issue_id=UUID("00000000-0000-0000-0000-000000000002"),
        category=CheckCategory.SECURITY,
        severity=IssueSeverity.INFO,
    )
    issue_third = build_issue(
        document,
        block_id="p-000002",
        original="absolute",
        suggestion="beta",
        start=5,
        end=13,
        page=2,
        issue_id=UUID("00000000-0000-0000-0000-000000000003"),
        category=CheckCategory.VOCABULARY,
        severity=IssueSeverity.WARNING,
    )

    repository.replace_analysis(job_id, document, [issue_third, issue_second, issue_first], {})
    db_session.commit()

    first_page = repository.list_issues(job_id, IssueQuery(limit=2))
    assert first_page.items == [issue_first, issue_second]
    assert first_page.total == 3
    assert first_page.next_cursor is not None

    second_page = repository.list_issues(job_id, IssueQuery(limit=2, cursor=first_page.next_cursor))
    assert second_page.items == [issue_third]
    assert second_page.total == 3
    assert second_page.next_cursor is None

    search_page = repository.list_issues(job_id, IssueQuery(search="absolute", limit=10))
    assert search_page.items == [issue_first, issue_third]

    filtered_page = repository.list_issues(
        job_id,
        IssueQuery(
            category=CheckCategory.SECURITY,
            severity=IssueSeverity.WARNING,
            limit=10,
        ),
    )
    assert filtered_page.items == [issue_first]


def seed_job(db_session: Session) -> UUID:
    now = datetime.now(UTC)
    job_id = uuid4()
    repository = JobRepository(db_session)
    repository.create_job(
        job_id=job_id,
        source_name="analysis.txt",
        file_type=FileType.TXT.value,
        size_bytes=16,
        storage_key=str(job_id),
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )
    repository.commit()
    return job_id


def build_document(block_specs: list[tuple[str, int | None]]) -> DocumentModel:
    blocks = [
        TextBlock(
            block_id=f"p-{index + 1:06d}",
            kind="paragraph",
            text=text,
            page=page,
            paragraph_index=index,
            parent_id=None,
            style={"style_name": "Normal"},
            source_locator={"paragraph_index": index},
        )
        for index, (text, page) in enumerate(block_specs)
    ]
    return DocumentModel(
        document_id=UUID("00000000-0000-0000-0000-000000000001"),
        file_type=FileType.TXT,
        source_name="analysis.txt",
        version=1,
        blocks=blocks,
        metadata={"language": "zh-CN"},
    )


def build_issue(
    document: DocumentModel,
    *,
    block_id: str,
    original: str,
    suggestion: str | None,
    start: int,
    end: int,
    page: int | None,
    issue_id: UUID | None = None,
    document_id: UUID | None = None,
    category: CheckCategory = CheckCategory.SECURITY,
    severity: IssueSeverity = IssueSeverity.WARNING,
    issue_type: str = "literal",
) -> Issue:
    return Issue(
        issue_id=issue_id or uuid4(),
        document_id=document_id or document.document_id,
        document_version=document.version,
        block_id=block_id,
        page=page,
        start=start,
        end=end,
        original=original,
        suggestion=suggestion,
        alternatives=[] if suggestion is None else [suggestion],
        type=issue_type,
        severity=severity,
        layer=category.value,
        message="命中规则。",
        rule_id=f"{category.value}-001",
        source="test",
        source_version="1",
        confidence=1.0,
        auto_fixable=suggestion is not None,
        context=original,
    )


def invalid_issue(*, document_id: UUID) -> Issue:
    return Issue(
        issue_id=uuid4(),
        document_id=document_id,
        block_id="missing-block",
        page=None,
        start=0,
        end=1,
        original="错",
        suggestion="正",
        alternatives=["正"],
        type="literal",
        severity=IssueSeverity.WARNING,
        layer=CheckCategory.SECURITY.value,
        message="缺少块映射。",
        rule_id="security-001",
        source="test",
        source_version="1",
        confidence=1.0,
        auto_fixable=True,
        context="错",
    )
