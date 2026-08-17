from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from text_verification.api.dependencies import get_db_session, get_job_storage
from text_verification.checkers.models import CheckCategory
from text_verification.domain.documents import DocumentModel, FileType, TextBlock
from text_verification.domain.exports import ExportType
from text_verification.domain.issues import Issue, IssueSeverity
from text_verification.domain.jobs import JobStatus
from text_verification.infrastructure.analysis_repositories import AnalysisRepository
from text_verification.infrastructure.export_repository import ExportRepository
from text_verification.infrastructure.orm import ExportRow
from text_verification.infrastructure.repositories import JobRepository
from text_verification.infrastructure.storage import JobStorage


@pytest.fixture
def export_storage(tmp_path: Path) -> JobStorage:
    root = tmp_path / "export-api-jobs"
    root.mkdir()
    return JobStorage(root, max_upload_bytes=25 * 1024 * 1024)


@pytest.fixture(autouse=True)
def export_api_dependencies(
    app: FastAPI,
    db_session_factory: sessionmaker[Session],
    export_storage: JobStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> list[str]:
    from text_verification.api.routes import exports as export_routes

    dispatched: list[str] = []

    def fresh_session():
        session = db_session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = fresh_session
    app.dependency_overrides[get_job_storage] = lambda: export_storage
    monkeypatch.setattr(
        export_routes,
        "dispatch_process_export",
        lambda export_id: dispatched.append(export_id),
    )
    return dispatched


def test_pdf_job_rejects_modified_document_export(client, db_session: Session) -> None:
    job_id = _seed_job_with_analysis(db_session, file_type=FileType.PDF)

    response = client.post(
        f"/api/v1/jobs/{job_id}/exports",
        json={"type": "modified_document"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "unsupported_export_type",
        "message": "该文件类型不支持所选导出格式。",
    }


def test_modified_document_requires_an_available_decision(
    client,
    db_session: Session,
) -> None:
    issue = _build_issue(file_type=FileType.TXT)
    job_id = _seed_job_with_analysis(
        db_session,
        file_type=FileType.TXT,
        issues=[issue],
    )

    response = client.post(
        f"/api/v1/jobs/{job_id}/exports",
        json={"type": "modified_document"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "export_decisions_required",
        "message": "请先处理至少一个问题，再导出修改版文件。",
    }


def test_reports_allow_unreviewed_issues_and_use_server_derived_extension(
    client,
    db_session: Session,
    export_api_dependencies: list[str],
) -> None:
    job_id = _seed_job_with_analysis(
        db_session,
        file_type=FileType.PDF,
        issues=[_build_issue(file_type=FileType.PDF)],
    )

    response = client.post(
        f"/api/v1/jobs/{job_id}/exports",
        json={"type": "html_report"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["job_id"] == str(job_id)
    assert payload["export_type"] == "html_report"
    assert payload["status"] == "queued"
    assert payload["file_name"] == "report.html"
    assert "storage_key" not in payload
    assert export_api_dependencies == [payload["export_id"]]


def test_export_dispatch_occurs_only_after_queued_row_is_committed(
    client,
    db_session: Session,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from text_verification.api.routes import exports as export_routes

    job_id = _seed_job_with_analysis(db_session, file_type=FileType.TXT)
    observed_statuses: list[str] = []

    def observe_committed_export(export_id: str) -> None:
        verification_session = db_session_factory()
        try:
            stored = ExportRepository(verification_session).get(UUID(export_id))
            assert stored is not None
            observed_statuses.append(stored.status.value)
        finally:
            verification_session.close()

    monkeypatch.setattr(export_routes, "dispatch_process_export", observe_committed_export)

    response = client.post(
        f"/api/v1/jobs/{job_id}/exports",
        json={"type": "html_report"},
    )

    assert response.status_code == 202
    assert observed_statuses == ["queued"]


def test_dispatch_failure_marks_export_failed_and_returns_structured_error(
    client,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from text_verification.api.routes import exports as export_routes

    job_id = _seed_job_with_analysis(db_session, file_type=FileType.TXT)

    def fail_dispatch(_export_id: str) -> None:
        raise ConnectionError("broker unavailable")

    monkeypatch.setattr(export_routes, "dispatch_process_export", fail_dispatch)

    response = client.post(
        f"/api/v1/jobs/{job_id}/exports",
        json={"type": "html_report"},
    )
    db_session.expire_all()
    stored = db_session.scalar(
        select(ExportRow)
        .where(ExportRow.job_id == job_id)
        .order_by(ExportRow.created_at.desc())
    )

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "export_dispatch_failed",
        "message": "暂时无法开始导出，请稍后重试。",
    }
    assert stored is not None
    assert stored.status == "failed"
    assert stored.error_code == "export_dispatch_failed"
    assert stored.error_message == "导出任务调度失败，请稍后重试。"


@pytest.mark.parametrize(
    ("status_value", "expected_status", "expected_code"),
    [
        (JobStatus.QUEUED, 409, "analysis_not_ready"),
        (JobStatus.FAILED, 409, "analysis_failed"),
        (JobStatus.EXPIRED, 410, "job_expired"),
    ],
)
def test_create_export_requires_known_terminal_analysis(
    client,
    db_session: Session,
    status_value: JobStatus,
    expected_status: int,
    expected_code: str,
) -> None:
    job_id = _seed_job(db_session, file_type=FileType.TXT, status=status_value)

    response = client.post(
        f"/api/v1/jobs/{job_id}/exports",
        json={"type": "html_report"},
    )

    assert response.status_code == expected_status
    assert response.json()["detail"]["code"] == expected_code


def test_create_export_rejects_terminal_job_without_persisted_analysis(
    client,
    db_session: Session,
) -> None:
    job_id = _seed_job(
        db_session,
        file_type=FileType.TXT,
        status=JobStatus.COMPLETED,
    )

    response = client.post(
        f"/api/v1/jobs/{job_id}/exports",
        json={"type": "html_report"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "analysis_not_ready",
        "message": "分析结果尚未就绪，请稍后重试。",
    }


def test_unknown_export_type_has_structured_error(client, db_session: Session) -> None:
    job_id = _seed_job_with_analysis(db_session, file_type=FileType.TXT)

    response = client.post(
        f"/api/v1/jobs/{job_id}/exports",
        json={"type": "server_archive"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "unsupported_export_type",
        "message": "不支持所选导出格式。",
    }


def test_export_status_is_scoped_to_job_and_omits_internal_storage_key(
    client,
    db_session: Session,
) -> None:
    first_job = _seed_job_with_analysis(db_session, file_type=FileType.TXT)
    second_job = _seed_job_with_analysis(db_session, file_type=FileType.TXT)
    export = ExportRepository(db_session).create(
        first_job,
        ExportType.HTML_REPORT,
        "html",
    )
    db_session.commit()

    found = client.get(f"/api/v1/jobs/{first_job}/exports/{export.export_id}")
    wrong_job = client.get(f"/api/v1/jobs/{second_job}/exports/{export.export_id}")

    assert found.status_code == 200
    assert found.json()["status"] == "queued"
    assert "storage_key" not in found.json()
    assert wrong_job.status_code == 404
    assert wrong_job.json()["detail"]["code"] == "export_not_found"


def test_download_returns_conflict_until_completed(client, db_session: Session) -> None:
    job_id = _seed_job_with_analysis(db_session, file_type=FileType.TXT)
    export = ExportRepository(db_session).create(
        job_id,
        ExportType.MODIFIED_DOCUMENT,
        "txt",
    )
    db_session.commit()

    response = client.get(
        f"/api/v1/jobs/{job_id}/exports/{export.export_id}/download"
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "export_not_ready",
        "message": "导出文件尚未生成，请稍后重试。",
    }


def test_download_returns_gone_after_expiry(
    client,
    db_session: Session,
) -> None:
    job_id = _seed_job_with_analysis(
        db_session,
        file_type=FileType.TXT,
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    repository = ExportRepository(db_session)
    export = repository.create(job_id, ExportType.MODIFIED_DOCUMENT, "txt")
    repository.mark_processing(export.export_id)
    repository.mark_completed(export.export_id, warnings=[])
    db_session.commit()

    response = client.get(
        f"/api/v1/jobs/{job_id}/exports/{export.export_id}/download"
    )

    assert response.status_code == 410
    assert response.json()["detail"] == {
        "code": "export_expired",
        "message": "导出文件已过期，请重新创建。",
    }


def test_download_serves_generated_path_with_rfc5987_filename(
    client,
    db_session: Session,
    export_storage: JobStorage,
) -> None:
    job_id = _seed_job_with_analysis(db_session, file_type=FileType.TXT)
    repository = ExportRepository(db_session)
    export = repository.create(job_id, ExportType.MODIFIED_DOCUMENT, "txt")
    repository.mark_processing(export.export_id)
    repository.mark_completed(export.export_id, warnings=[])
    db_session.commit()
    export_path = export_storage.export_path(job_id, export.export_id, "txt")
    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_path.write_bytes("修改后的正文\n".encode())

    response = client.get(
        f"/api/v1/jobs/{job_id}/exports/{export.export_id}/download"
    )

    assert response.status_code == 200
    assert response.content.decode("utf-8") == "修改后的正文\n"
    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers["content-disposition"] == (
        "attachment; filename=\"modified_document.txt\"; "
        "filename*=UTF-8''modified_document.txt"
    )
    assert str(export_storage.job_directory(job_id)) not in str(response.headers)


def test_download_fails_closed_when_job_directory_escapes_storage_root(
    client,
    db_session: Session,
    export_storage: JobStorage,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = _seed_job_with_analysis(db_session, file_type=FileType.TXT)
    repository = ExportRepository(db_session)
    export = repository.create(job_id, ExportType.MODIFIED_DOCUMENT, "txt")
    repository.mark_processing(export.export_id)
    repository.mark_completed(export.export_id, warnings=[])
    db_session.commit()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / f"{export.export_id}.txt").write_text("secret", encoding="utf-8")
    monkeypatch.setattr(export_storage, "job_directory", lambda _job_id: outside)

    response = client.get(
        f"/api/v1/jobs/{job_id}/exports/{export.export_id}/download"
    )

    assert response.status_code == 410
    assert response.json()["detail"] == {
        "code": "export_file_unavailable",
        "message": "导出文件不可用，请重新创建。",
    }


def _seed_job_with_analysis(
    session: Session,
    *,
    file_type: FileType,
    issues: list[Issue] | None = None,
    expires_at: datetime | None = None,
) -> UUID:
    job_id = _seed_job(
        session,
        file_type=file_type,
        status=JobStatus.COMPLETED,
        expires_at=expires_at,
    )
    document = _build_document(
        file_type=file_type,
        document_id=issues[0].document_id if issues else None,
    )
    AnalysisRepository(session).replace_analysis(job_id, document, issues or [], {})
    session.commit()
    return job_id


def _seed_job(
    session: Session,
    *,
    file_type: FileType,
    status: JobStatus,
    expires_at: datetime | None = None,
) -> UUID:
    now = datetime.now(UTC)
    job_id = uuid4()
    repository = JobRepository(session)
    repository.create_job(
        job_id=job_id,
        source_name=f"sample.{file_type.value}",
        file_type=file_type.value,
        size_bytes=16,
        storage_key=str(job_id),
        created_at=now,
        expires_at=expires_at or now + timedelta(hours=1),
    )
    if status != JobStatus.QUEUED:
        repository.transition(
            job_id,
            status,
            100 if status in {JobStatus.COMPLETED, JobStatus.PARTIAL} else 0,
            "处理完成",
            error_code="analysis_failed" if status == JobStatus.FAILED else None,
            error_message="分析失败。" if status == JobStatus.FAILED else None,
        )
    repository.commit()
    return job_id


def _build_document(
    *,
    file_type: FileType,
    document_id: UUID | None = None,
) -> DocumentModel:
    return DocumentModel(
        document_id=document_id or uuid4(),
        file_type=file_type,
        source_name=f"sample.{file_type.value}",
        version=1,
        blocks=[
            TextBlock(
                block_id="p-000001",
                kind="paragraph",
                text="原始正文",
                page=1 if file_type == FileType.PDF else None,
                paragraph_index=0,
                parent_id=None,
                style={},
                source_locator={"paragraph_index": 0},
            )
        ],
        metadata={},
    )


def _build_issue(*, file_type: FileType) -> Issue:
    return Issue(
        issue_id=uuid4(),
        document_id=uuid4(),
        block_id="p-000001",
        page=1 if file_type == FileType.PDF else None,
        start=0,
        end=2,
        original="原始",
        suggestion="修改后的",
        alternatives=["修改后的"],
        type="literal",
        severity=IssueSeverity.WARNING,
        layer=CheckCategory.CHARACTER.value,
        message="命中规则。",
        rule_id="character-001",
        source="test",
        source_version="1",
        confidence=1.0,
        auto_fixable=True,
        context="原始正文",
    )
