from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy.orm import Session

from text_verification.api.dependencies import get_db_session
from text_verification.checkers.models import CheckCategory, CheckerFailure
from text_verification.domain.documents import DocumentModel, FileType, TextBlock
from text_verification.domain.issues import Issue, IssueSeverity
from text_verification.domain.jobs import JobStatus
from text_verification.infrastructure.analysis_repositories import AnalysisRepository
from text_verification.infrastructure.repositories import JobRepository


@pytest.fixture(autouse=True)
def override_db_session(app: FastAPI, db_session: Session) -> None:
    def _db_session_override():
        yield db_session

    app.dependency_overrides[get_db_session] = _db_session_override


def test_analysis_endpoints_paginate_and_summarize_completed_results(
    client,
    db_session: Session,
) -> None:
    job_id = _seed_analysis(
        db_session,
        status=JobStatus.COMPLETED,
        document=_build_document([("第一段", 1), ("第二段", 2)]),
        issues=[
            _build_issue(
                block_id="p-000001",
                issue_id=UUID("00000000-0000-0000-0000-000000000001"),
                original="第一",
                suggestion="首段",
                start=0,
                end=2,
                page=1,
                category=CheckCategory.SECURITY,
                severity=IssueSeverity.WARNING,
            ),
            _build_issue(
                block_id="p-000002",
                issue_id=UUID("00000000-0000-0000-0000-000000000002"),
                original="第二",
                suggestion=None,
                start=0,
                end=2,
                page=2,
                category=CheckCategory.VOCABULARY,
                severity=IssueSeverity.INFO,
            ),
        ],
        failures={},
    )

    document_response = client.get(f"/api/v1/jobs/{job_id}/document", params={"limit": 1})
    assert document_response.status_code == 200
    document_payload = document_response.json()
    assert document_payload["job_id"] == str(job_id)
    assert document_payload["status"] == "completed"
    assert document_payload["total_blocks"] == 2
    assert [block["block_id"] for block in document_payload["blocks"]] == ["p-000001"]
    assert document_payload["next_cursor"] is not None
    assert document_payload["checker_failures"] == {}

    second_document_response = client.get(
        f"/api/v1/jobs/{job_id}/document",
        params={"limit": 1, "cursor": f"  {document_payload['next_cursor']}  "},
    )
    assert second_document_response.status_code == 200
    assert [block["block_id"] for block in second_document_response.json()["blocks"]] == [
        "p-000002"
    ]

    issues_response = client.get(f"/api/v1/jobs/{job_id}/issues", params={"limit": 1})
    assert issues_response.status_code == 200
    issues_payload = issues_response.json()
    assert issues_payload["job_id"] == str(job_id)
    assert issues_payload["status"] == "completed"
    assert issues_payload["total"] == 2
    assert [item["rule_id"] for item in issues_payload["items"]] == ["security-001"]
    assert issues_payload["next_cursor"] is not None
    assert issues_payload["checker_failures"] == {}

    second_issues_response = client.get(
        f"/api/v1/jobs/{job_id}/issues",
        params={"limit": 1, "cursor": f"  {issues_payload['next_cursor']}  "},
    )
    assert second_issues_response.status_code == 200
    assert [item["rule_id"] for item in second_issues_response.json()["items"]] == [
        "vocabulary-001"
    ]

    summary_response = client.get(f"/api/v1/jobs/{job_id}/summary")
    assert summary_response.status_code == 200
    summary_payload = summary_response.json()
    assert summary_payload["job_id"] == str(job_id)
    assert summary_payload["status"] == "completed"
    assert summary_payload["total_issues"] == 2
    assert summary_payload["by_category"]["security"] == 1
    assert summary_payload["by_category"]["vocabulary"] == 1
    assert summary_payload["by_severity"]["warning"] == 1
    assert summary_payload["by_severity"]["info"] == 1
    assert summary_payload["checker_failures"] == {}


def test_partial_analysis_endpoints_include_checker_failures(client, db_session: Session) -> None:
    job_id = _seed_analysis(
        db_session,
        status=JobStatus.PARTIAL,
        document=_build_document([("保留结果", 3)]),
        issues=[
            _build_issue(
                block_id="p-000001",
                original="保留",
                suggestion="保存",
                start=0,
                end=2,
                page=3,
                category=CheckCategory.CHARACTER,
            )
        ],
        failures={
            CheckCategory.SENTENCE: CheckerFailure(
                code="checker_failed",
                message="句子检查暂时不可用。",
            )
        },
    )

    document_response = client.get(f"/api/v1/jobs/{job_id}/document")
    issues_response = client.get(f"/api/v1/jobs/{job_id}/issues")
    summary_response = client.get(f"/api/v1/jobs/{job_id}/summary")

    assert document_response.status_code == 200
    assert issues_response.status_code == 200
    assert summary_response.status_code == 200
    assert document_response.json()["status"] == "partial"
    assert issues_response.json()["status"] == "partial"
    assert summary_response.json()["status"] == "partial"
    assert summary_response.json()["checker_failures"] == {
        "sentence": {"code": "checker_failed", "message": "句子检查暂时不可用。"}
    }
    assert (
        document_response.json()["checker_failures"]
        == summary_response.json()["checker_failures"]
    )
    assert issues_response.json()["checker_failures"] == summary_response.json()[
        "checker_failures"
    ]


def test_analysis_endpoints_return_ready_and_not_found_errors(client, db_session: Session) -> None:
    queued_job_id = _seed_job(db_session, status=JobStatus.QUEUED)

    ready_response = client.get(f"/api/v1/jobs/{queued_job_id}/summary")
    missing_response = client.get("/api/v1/jobs/00000000-0000-0000-0000-000000000000/document")

    assert ready_response.status_code == 409
    assert ready_response.json()["detail"]["code"] == "analysis_not_ready"
    assert missing_response.status_code == 404
    assert missing_response.json()["detail"]["code"] == "job_not_found"


@pytest.mark.parametrize("path_suffix", ["document", "issues", "summary"])
@pytest.mark.parametrize(
    ("status", "error_code", "message"),
    [
        (JobStatus.QUEUED, "analysis_not_ready", "分析结果尚未就绪，请稍后重试。"),
        (JobStatus.PARSING, "analysis_not_ready", "分析结果尚未就绪，请稍后重试。"),
        (JobStatus.FAILED, "analysis_failed", "PDF 中没有可提取的文本，请使用包含文本层的 PDF。"),
        (JobStatus.EXPIRED, "job_expired", "作业已过期，请重新上传文件。"),
    ],
)
def test_analysis_routes_guard_non_ready_terminal_statuses(
    client,
    db_session: Session,
    path_suffix: str,
    status: JobStatus,
    error_code: str,
    message: str,
) -> None:
    job_id = _seed_job(
        db_session,
        status=status,
        error_message=(
            "PDF 中没有可提取的文本，请使用包含文本层的 PDF。"
            if status == JobStatus.FAILED
            else None
        ),
    )

    response = client.get(f"/api/v1/jobs/{job_id}/{path_suffix}")

    expected_status_code = 410 if status == JobStatus.EXPIRED else 409
    assert response.status_code == expected_status_code
    assert response.json()["detail"] == {"code": error_code, "message": message}


def test_analysis_endpoints_reject_malformed_cursors_with_chinese_errors(
    client,
    db_session: Session,
) -> None:
    job_id = _seed_analysis(
        db_session,
        status=JobStatus.COMPLETED,
        document=_build_document([("正文", 1)]),
        issues=[
            _build_issue(
                block_id="p-000001",
                original="正文",
                suggestion="正文",
                start=0,
                end=2,
                page=1,
                category=CheckCategory.SECURITY,
            )
        ],
        failures={},
    )

    document_response = client.get(
        f"/api/v1/jobs/{job_id}/document",
        params={"cursor": "not-base64"},
    )
    issues_response = client.get(
        f"/api/v1/jobs/{job_id}/issues",
        params={"cursor": "eyJmb28iOiJiYXIifQ"},
    )

    assert document_response.status_code == 400
    assert document_response.json()["detail"] == {
        "code": "invalid_document_cursor",
        "message": "文档分页游标无效，请刷新后重试。",
    }
    assert "base64" not in document_response.text.lower()
    assert "json" not in document_response.text.lower()

    assert issues_response.status_code == 400
    assert issues_response.json()["detail"] == {
        "code": "invalid_issue_cursor",
        "message": "问题分页游标无效，请刷新后重试。",
    }
    assert "uuid" not in issues_response.text.lower()
    assert "json" not in issues_response.text.lower()


def _seed_analysis(
    db_session: Session,
    *,
    status: JobStatus,
    document: DocumentModel,
    issues: list[Issue],
    failures: dict[CheckCategory, CheckerFailure],
) -> UUID:
    job_id = _seed_job(db_session, status=status)
    repository = AnalysisRepository(db_session)
    repository.replace_analysis(job_id, document, issues, failures)
    db_session.commit()
    return job_id


def _seed_job(
    db_session: Session,
    *,
    status: JobStatus,
    error_message: str | None = None,
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
            (
                "处理完成"
                if status in {JobStatus.COMPLETED, JobStatus.PARTIAL}
                else "作业已过期" if status == JobStatus.EXPIRED else "处理失败"
                if status == JobStatus.FAILED
                else "处理中"
            ),
            error_code="pipeline_failed" if status == JobStatus.FAILED else None,
            error_message=error_message,
        )
    repository.commit()
    return job_id


def _build_document(block_specs: list[tuple[str, int | None]]) -> DocumentModel:
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


def _build_issue(
    *,
    block_id: str,
    original: str,
    suggestion: str | None,
    start: int,
    end: int,
    page: int | None,
    category: CheckCategory,
    severity: IssueSeverity = IssueSeverity.WARNING,
    issue_id: UUID | None = None,
) -> Issue:
    return Issue(
        issue_id=issue_id or uuid4(),
        document_id=UUID("00000000-0000-0000-0000-000000000001"),
        block_id=block_id,
        page=page,
        start=start,
        end=end,
        original=original,
        suggestion=suggestion,
        alternatives=[] if suggestion is None else [suggestion],
        type="literal",
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
