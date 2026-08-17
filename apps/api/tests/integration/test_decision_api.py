from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from text_verification.api.dependencies import get_db_session
from text_verification.checkers.models import CheckCategory
from text_verification.domain.documents import DocumentModel, FileType, TextBlock
from text_verification.domain.issues import Issue, IssueSeverity
from text_verification.domain.jobs import JobStatus
from text_verification.infrastructure.analysis_repositories import AnalysisRepository
from text_verification.infrastructure.orm import IssueDecisionRow, IssueRow
from text_verification.infrastructure.repositories import JobRepository


@dataclass(frozen=True)
class SeededIssue:
    issue_id: UUID
    document_version: int


def test_batch_decisions_return_per_item_outcomes_in_request_order(
    client,
    db_session: Session,
) -> None:
    job_id, current_issue, stale_issue = _seed_two_versioned_issues(db_session)

    response = client.put(
        f"/api/v1/jobs/{job_id}/decisions",
        json={
            "decisions": [
                {
                    "issue_id": str(current_issue.issue_id),
                    "issue_version": current_issue.document_version,
                    "action": "accepted",
                    "replacement": None,
                },
                {
                    "issue_id": str(stale_issue.issue_id),
                    "issue_version": stale_issue.document_version,
                    "action": "ignored",
                    "replacement": None,
                },
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert [item["status"] for item in payload["outcomes"]] == ["applied", "conflict"]
    assert payload["outcomes"][0]["issue_id"] == str(current_issue.issue_id)
    assert payload["outcomes"][0]["decision"]["issue_id"] == str(current_issue.issue_id)
    assert payload["outcomes"][0]["decision"]["issue_version"] == current_issue.document_version
    assert payload["outcomes"][0]["decision"]["action"] == "accepted"
    assert payload["outcomes"][0]["decision"]["replacement"] is None
    assert payload["outcomes"][1] == {
        "issue_id": str(stale_issue.issue_id),
        "status": "conflict",
        "code": "stale_issue_version",
        "decision": None,
    }
    assert _count_decisions(db_session, current_issue.issue_id) == 1


def test_batch_decisions_reject_duplicate_issue_ids_with_structured_error(
    client,
    db_session: Session,
) -> None:
    job_id, current_issue, _stale_issue = _seed_two_versioned_issues(db_session)

    response = client.put(
        f"/api/v1/jobs/{job_id}/decisions",
        json={
            "decisions": [
                {
                    "issue_id": str(current_issue.issue_id),
                    "issue_version": current_issue.document_version,
                    "action": "accepted",
                    "replacement": None,
                },
                {
                    "issue_id": str(current_issue.issue_id),
                    "issue_version": current_issue.document_version,
                    "action": "ignored",
                    "replacement": None,
                },
            ]
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "duplicate_issue_decision",
        "message": "同一请求中不能重复提交同一问题的决策。",
    }
    assert _count_decisions(db_session, current_issue.issue_id) == 0


def test_batch_decisions_require_known_job_with_analysis(client, db_session: Session) -> None:
    ready_without_analysis = _seed_job(db_session, status=JobStatus.COMPLETED)
    payload = {
        "decisions": [
            {
                "issue_id": str(uuid4()),
                "issue_version": 1,
                "action": "accepted",
                "replacement": None,
            }
        ]
    }

    missing_response = client.put(
        "/api/v1/jobs/00000000-0000-0000-0000-000000000000/decisions",
        json=payload,
    )
    not_ready_response = client.put(
        f"/api/v1/jobs/{ready_without_analysis}/decisions",
        json=payload,
    )

    assert missing_response.status_code == 404
    assert missing_response.json()["detail"] == {
        "code": "job_not_found",
        "message": "作业不存在。",
    }
    assert not_ready_response.status_code == 409
    assert not_ready_response.json()["detail"] == {
        "code": "analysis_not_ready",
        "message": "分析结果尚未就绪，请稍后重试。",
    }


def test_batch_decisions_reject_more_than_500_items(client) -> None:
    response = client.put(
        "/api/v1/jobs/00000000-0000-0000-0000-000000000000/decisions",
        json={
            "decisions": [
                {
                    "issue_id": str(uuid4()),
                    "issue_version": 1,
                    "action": "accepted",
                    "replacement": None,
                }
                for _ in range(501)
            ]
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "invalid_decision_request",
        "message": "问题决策请求无效，请检查后重试。",
    }


def _seed_two_versioned_issues(db_session: Session) -> tuple[UUID, SeededIssue, SeededIssue]:
    job_id = _seed_job(db_session, status=JobStatus.COMPLETED)
    repository = AnalysisRepository(db_session)
    stale_document = _build_document(version=1, text="旧问题")
    stale_issue = _build_issue(
        document=stale_document,
        issue_id=UUID("00000000-0000-0000-0000-000000000021"),
        original="旧",
        suggestion="新",
    )
    repository.replace_analysis(job_id, stale_document, [stale_issue], {})
    db_session.commit()

    current_document = _build_document(version=2, text="当前问题")
    current_issue = _build_issue(
        document=current_document,
        issue_id=UUID("00000000-0000-0000-0000-000000000022"),
        original="当前",
        suggestion="最新",
    )
    repository.replace_analysis(job_id, current_document, [current_issue], {})
    db_session.commit()

    current_issue_row = db_session.get(IssueRow, current_issue.issue_id)
    assert current_issue_row is not None
    return (
        job_id,
        SeededIssue(
            issue_id=current_issue_row.issue_id,
            document_version=current_issue_row.document_version,
        ),
        SeededIssue(
            issue_id=stale_issue.issue_id,
            document_version=stale_document.version,
        ),
    )


def _count_decisions(db_session: Session, issue_id: UUID) -> int:
    return int(
        db_session.scalar(
            select(func.count())
            .select_from(IssueDecisionRow)
            .where(IssueDecisionRow.issue_id == issue_id)
        )
        or 0
    )


def _seed_job(
    db_session: Session,
    *,
    status: JobStatus,
) -> UUID:
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
    if status != JobStatus.QUEUED:
        repository.transition(
            job_id,
            status,
            100 if status in {JobStatus.COMPLETED, JobStatus.PARTIAL} else 0,
            "处理完成" if status in {JobStatus.COMPLETED, JobStatus.PARTIAL} else "处理中",
        )
    repository.commit()
    return job_id


def _build_document(*, version: int, text: str) -> DocumentModel:
    return DocumentModel(
        document_id=UUID("00000000-0000-0000-0000-000000000001"),
        file_type=FileType.TXT,
        source_name="analysis.txt",
        version=version,
        blocks=[
            TextBlock(
                block_id="p-000001",
                kind="paragraph",
                text=text,
                page=1,
                paragraph_index=0,
                parent_id=None,
                style={"style_name": "Normal"},
                source_locator={"paragraph_index": 0},
            )
        ],
        metadata={"language": "zh-CN"},
    )


def _build_issue(
    *,
    document: DocumentModel,
    issue_id: UUID,
    original: str,
    suggestion: str | None,
) -> Issue:
    return Issue(
        issue_id=issue_id,
        document_id=document.document_id,
        block_id="p-000001",
        page=1,
        start=0,
        end=len(original),
        original=original,
        suggestion=suggestion,
        alternatives=[] if suggestion is None else [suggestion],
        type="literal",
        severity=IssueSeverity.WARNING,
        layer=CheckCategory.SECURITY.value,
        message="命中规则。",
        rule_id="security-001",
        source="test",
        source_version="1",
        confidence=1.0,
        auto_fixable=suggestion is not None,
        context=original,
    )


@pytest.fixture(autouse=True)
def override_db_session(app: FastAPI, db_session: Session) -> None:
    def _db_session_override():
        yield db_session

    app.dependency_overrides[get_db_session] = _db_session_override
