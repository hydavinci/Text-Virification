from __future__ import annotations

from datetime import UTC, datetime, timedelta
from importlib import import_module
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from text_verification.checkers.models import CheckCategory
from text_verification.domain.documents import DocumentModel, FileType, TextBlock
from text_verification.domain.issues import Issue, IssueSeverity
from text_verification.infrastructure.analysis_repositories import AnalysisRepository
from text_verification.infrastructure.orm import IssueRow
from text_verification.infrastructure.repositories import JobRepository


@pytest.fixture
def postgres_session(db_session: Session) -> Session:
    return db_session


@pytest.mark.parametrize(
    ("action_name", "replacement", "suggestion_id"),
    [
        ("ACCEPTED", None, None),
        ("ACCEPTED", "   ", None),
        ("ACCEPTED", "\t", None),
        ("ACCEPTED", "\n", None),
        ("ACCEPTED", "before\0after", None),
        ("ACCEPTED", "🙂" * 10_001, None),
        ("IGNORED", "replacement", None),
        ("IGNORED", None, uuid4()),
    ],
    ids=[
        "accepted-none",
        "accepted-spaces",
        "accepted-tab",
        "accepted-newline",
        "accepted-nul",
        "accepted-over-limit",
        "ignored-with-replacement",
        "ignored-with-suggestion-id",
    ],
)
def test_decision_rejects_invalid_replacement(
    action_name: str,
    replacement: str | None,
    suggestion_id: UUID | None,
) -> None:
    DecisionAction, DecisionCommand, *_ = _decision_symbols()
    with pytest.raises(ValidationError):
        DecisionCommand(
            issue_id=uuid4(),
            issue_version=1,
            expected_revision=0,
            action=getattr(DecisionAction, action_name),
            replacement=replacement,
            suggestion_id=suggestion_id,
        )


def test_decision_accepts_accepted_replacement_at_10_000_code_point_boundary() -> None:
    DecisionAction, DecisionCommand, *_ = _decision_symbols()

    command = DecisionCommand(
        issue_id=uuid4(),
        issue_version=1,
        expected_revision=0,
        action=DecisionAction.ACCEPTED,
        replacement="🙂" * 10_000,
    )

    assert command.replacement is not None
    assert len(command.replacement) == 10_000


def test_apply_rejects_stale_issue_version(postgres_session: Session) -> None:
    DecisionAction, DecisionCommand, DecisionRepository, DecisionOutcomeStatus, _ = (
        _decision_symbols()
    )
    job_id, issue = seed_issue(postgres_session, document_version=2)

    outcome = DecisionRepository(postgres_session).apply(
        job_id,
        DecisionCommand(
            issue_id=issue.issue_id,
            issue_version=1,
            expected_revision=0,
            action=DecisionAction.ACCEPTED,
            replacement=issue.suggestion,
        ),
    )

    assert outcome.status == DecisionOutcomeStatus.CONFLICT
    assert outcome.code == "stale_issue_version"
    assert outcome.decision is None
    assert count_decisions(postgres_session, issue.issue_id) == 0


def test_apply_returns_conflict_for_removed_issue_from_stale_document_version(
    postgres_session: Session,
) -> None:
    DecisionAction, DecisionCommand, DecisionRepository, DecisionOutcomeStatus, _ = (
        _decision_symbols()
    )
    job_id, stale_issue = seed_issue(postgres_session, document_version=1)

    AnalysisRepository(postgres_session).replace_analysis(
        job_id,
        build_document(document_version=2),
        [],
        {},
    )
    postgres_session.commit()

    outcome = DecisionRepository(postgres_session).apply(
        job_id,
        DecisionCommand(
            issue_id=stale_issue.issue_id,
            issue_version=stale_issue.document_version,
            expected_revision=0,
            action=DecisionAction.IGNORED,
        ),
    )

    assert outcome.status == DecisionOutcomeStatus.CONFLICT
    assert outcome.code == "stale_issue_version"
    assert outcome.decision is None
    assert count_decisions(postgres_session, stale_issue.issue_id) == 0


def test_apply_same_decision_requires_current_revision(postgres_session: Session) -> None:
    DecisionAction, DecisionCommand, DecisionRepository, DecisionOutcomeStatus, _ = (
        _decision_symbols()
    )
    job_id, issue = seed_issue(postgres_session, document_version=1)
    command = DecisionCommand(
        issue_id=issue.issue_id,
        issue_version=1,
        expected_revision=0,
        action=DecisionAction.IGNORED,
    )
    repository = DecisionRepository(postgres_session)

    first = repository.apply(job_id, command)
    assert first.decision is not None
    second = repository.apply(
        job_id,
        command.model_copy(update={"expected_revision": first.decision.revision}),
    )
    postgres_session.commit()

    assert first.status == DecisionOutcomeStatus.APPLIED
    assert second.status == DecisionOutcomeStatus.APPLIED
    assert first.decision is not None
    assert second.decision is not None
    assert second.decision.action == first.decision.action
    assert second.decision.revision == first.decision.revision + 1
    assert count_decisions(postgres_session, issue.issue_id) == 1


def test_apply_updates_existing_decision_when_command_revision_is_current(
    postgres_session: Session,
) -> None:
    DecisionAction, DecisionCommand, DecisionRepository, DecisionOutcomeStatus, _ = (
        _decision_symbols()
    )
    job_id, issue = seed_issue(postgres_session, document_version=1)
    repository = DecisionRepository(postgres_session)

    first = repository.apply(
        job_id,
        DecisionCommand(
            issue_id=issue.issue_id,
            issue_version=issue.document_version,
            expected_revision=0,
            action=DecisionAction.ACCEPTED,
            replacement=issue.suggestion,
        ),
    )
    assert first.decision is not None
    second = repository.apply(
        job_id,
        DecisionCommand(
            issue_id=issue.issue_id,
            issue_version=issue.document_version,
            expected_revision=first.decision.revision,
            action=DecisionAction.ACCEPTED,
            replacement="建议文本",
        ),
    )
    postgres_session.commit()

    assert first.status == DecisionOutcomeStatus.APPLIED
    assert second.status == DecisionOutcomeStatus.APPLIED
    assert first.decision is not None
    assert second.decision is not None
    assert first.decision.action == DecisionAction.ACCEPTED
    assert second.decision.action == DecisionAction.ACCEPTED
    assert second.decision.replacement == "建议文本"
    assert count_decisions(postgres_session, issue.issue_id) == 1


def test_apply_returns_invalid_outcome_for_unknown_current_version_issue(
    postgres_session: Session,
) -> None:
    DecisionAction, DecisionCommand, DecisionRepository, DecisionOutcomeStatus, _ = (
        _decision_symbols()
    )
    job_id, issue = seed_issue(postgres_session, document_version=2)

    outcome = DecisionRepository(postgres_session).apply(
        job_id,
        DecisionCommand(
            issue_id=uuid4(),
            issue_version=issue.document_version,
            expected_revision=0,
            action=DecisionAction.IGNORED,
        ),
    )

    assert outcome.status == DecisionOutcomeStatus.INVALID
    assert outcome.code == "issue_not_found"
    assert outcome.decision is None


@pytest.mark.parametrize("replacement", ["\t", "\n", "\r\n\t"])
def test_issue_decision_table_rejects_whitespace_only_accepted_replacement(
    postgres_session: Session,
    replacement: str,
) -> None:
    *_, IssueDecisionRow = _decision_symbols()
    job_id, issue = seed_issue(postgres_session, document_version=1)

    postgres_session.add(
        IssueDecisionRow(
            issue_id=issue.issue_id,
            version_id=issue.version_id,
            job_id=job_id,
            issue_version=issue.document_version,
            action="accepted",
            replacement=replacement,
            final_replacement=None,
            updated_at=datetime.now(UTC),
        )
    )

    with pytest.raises(IntegrityError, match="ck_issue_decisions_action_replacement"):
        postgres_session.flush()

    postgres_session.rollback()
    assert count_decisions(postgres_session, issue.issue_id) == 0


def _decision_symbols() -> tuple[Any, Any, Any, Any, Any]:
    try:
        issues_module = import_module("text_verification.domain.issues")
        repository_module = import_module("text_verification.infrastructure.decision_repository")
        orm_module = import_module("text_verification.infrastructure.orm")
    except ModuleNotFoundError as error:
        pytest.fail(f"Decision persistence is not implemented yet: {error}")

    try:
        return (
            issues_module.DecisionAction,
            issues_module.DecisionCommand,
            repository_module.DecisionRepository,
            repository_module.DecisionOutcomeStatus,
            orm_module.IssueDecisionRow,
        )
    except AttributeError as error:
        pytest.fail(f"Decision persistence is not implemented yet: {error}")


def count_decisions(postgres_session: Session, issue_id: UUID) -> int:
    *_, IssueDecisionRow = _decision_symbols()
    return int(
        postgres_session.scalar(
            select(func.count())
            .select_from(IssueDecisionRow)
            .where(IssueDecisionRow.issue_id == issue_id)
        )
        or 0
    )


def seed_issue(
    postgres_session: Session,
    *,
    document_version: int,
) -> tuple[UUID, IssueRow]:
    repository = AnalysisRepository(postgres_session)
    job_id = seed_job(postgres_session)
    document = build_document(document_version=document_version)
    issue = build_issue(document)

    repository.replace_analysis(job_id, document, [issue], {})
    postgres_session.commit()

    stored_issue = postgres_session.get(IssueRow, issue.issue_id)
    assert stored_issue is not None
    return job_id, stored_issue


def seed_job(postgres_session: Session) -> UUID:
    now = datetime.now(UTC)
    job_id = uuid4()
    repository = JobRepository(postgres_session)
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


def build_document(*, document_version: int) -> DocumentModel:
    return DocumentModel(
        document_id=UUID("00000000-0000-0000-0000-000000000001"),
        file_type=FileType.TXT,
        source_name="analysis.txt",
        version=document_version,
        blocks=[
            TextBlock(
                block_id="p-000001",
                kind="paragraph",
                text="绝对领先",
                page=1,
                paragraph_index=0,
                parent_id=None,
                style={"style_name": "Normal"},
                source_locator={"paragraph_index": 0},
            )
        ],
        metadata={"language": "zh-CN"},
    )


def build_issue(document: DocumentModel) -> Issue:
    return Issue(
        issue_id=uuid4(),
        document_id=document.document_id,
        block_id="p-000001",
        page=1,
        start=0,
        end=4,
        original="绝对领先",
        suggestion="领先",
        alternatives=["领先"],
        type="literal",
        severity=IssueSeverity.WARNING,
        layer=CheckCategory.SECURITY.value,
        message="命中规则。",
        rule_id="security-001",
        source="test",
        source_version="1",
        confidence=1.0,
        auto_fixable=True,
        context="绝对领先",
    )
