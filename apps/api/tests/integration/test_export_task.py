from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from docx import Document as WordDocument
from fastapi import FastAPI
from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from text_verification.api.dependencies import get_db_session, get_job_storage
from text_verification.checkers.models import CheckCategory, CheckerFailure
from text_verification.domain.documents import DocumentModel, FileType
from text_verification.domain.exports import ExportStatus
from text_verification.domain.issues import (
    DecisionAction,
    DecisionCommand,
    Issue,
    IssueSeverity,
)
from text_verification.domain.jobs import JobStatus
from text_verification.exporters import ExportError, TxtExporter
from text_verification.infrastructure.analysis_repositories import AnalysisRepository
from text_verification.infrastructure.decision_repository import DecisionRepository
from text_verification.infrastructure.export_repository import ExportRepository
from text_verification.infrastructure.orm import IssueDecisionRow
from text_verification.infrastructure.repositories import JobRepository
from text_verification.infrastructure.storage import JobStorage
from text_verification.parsers import DocxParser, TxtParser


@pytest.fixture
def celery_eager() -> None:
    from text_verification.workers.celery_app import celery_app

    original_values = {
        "task_always_eager": celery_app.conf.task_always_eager,
        "task_store_eager_result": celery_app.conf.task_store_eager_result,
        "task_eager_propagates": celery_app.conf.task_eager_propagates,
    }
    celery_app.conf.update(
        task_always_eager=True,
        task_store_eager_result=False,
        task_eager_propagates=False,
    )
    try:
        yield
    finally:
        celery_app.conf.update(**original_values)


@pytest.fixture
def export_storage(tmp_path: Path) -> JobStorage:
    root = tmp_path / "export-task-jobs"
    root.mkdir()
    return JobStorage(root, max_upload_bytes=25 * 1024 * 1024)


@pytest.fixture(autouse=True)
def export_task_dependencies(
    app: FastAPI,
    db_session_factory: sessionmaker[Session],
    export_storage: JobStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from text_verification.workers import export_tasks

    def fresh_session():
        session = db_session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = fresh_session
    app.dependency_overrides[get_job_storage] = lambda: export_storage
    monkeypatch.setattr(
        export_tasks,
        "SESSION_FACTORY_PROVIDER",
        lambda: db_session_factory,
    )
    monkeypatch.setattr(export_tasks, "STORAGE_FACTORY", lambda: export_storage)


def test_txt_export_task_completes_round_trips_and_downloads(
    client,
    celery_eager,
    db_session: Session,
    db_session_factory: sessionmaker[Session],
    export_storage: JobStorage,
) -> None:
    job_id, issue = _seed_reviewed_txt_job(db_session, export_storage)
    other_job_id = _seed_empty_job(
        db_session,
        file_type=FileType.TXT,
        status=JobStatus.COMPLETED,
    )
    db_session.execute(
        update(IssueDecisionRow)
        .where(IssueDecisionRow.issue_id == issue.issue_id)
        .values(job_id=other_job_id)
    )
    db_session.commit()

    created = client.post(
        f"/api/v1/jobs/{job_id}/exports",
        json={"type": "modified_document"},
    )
    export_id = UUID(created.json()["export_id"])
    status_response = client.get(f"/api/v1/jobs/{job_id}/exports/{export_id}")
    download = client.get(f"/api/v1/jobs/{job_id}/exports/{export_id}/download")

    assert created.status_code == 202
    assert status_response.json()["status"] == "completed"
    assert download.status_code == 200
    assert download.content.decode("utf-8") == "修改后的正文\n"
    stored_path = export_storage.export_path(job_id, export_id, "txt")
    reparsed = TxtParser().parse(
        stored_path,
        document_id=uuid4(),
        source_name="modified_document.txt",
    )
    assert [block.text for block in reparsed.blocks] == ["修改后的正文"]
    stored = _load_export(db_session_factory, export_id)
    assert stored.status == ExportStatus.COMPLETED
    assert stored.warnings == []


def test_docx_export_task_round_trips_safe_changes_and_preserves_skipped_warning(
    client,
    celery_eager,
    db_session: Session,
    db_session_factory: sessionmaker[Session],
    export_storage: JobStorage,
) -> None:
    job_id, unsafe_issue = _seed_reviewed_docx_job(db_session, export_storage)

    created = client.post(
        f"/api/v1/jobs/{job_id}/exports",
        json={"type": "modified_document"},
    )
    export_id = UUID(created.json()["export_id"])
    download = client.get(f"/api/v1/jobs/{job_id}/exports/{export_id}/download")

    assert created.status_code == 202
    assert download.status_code == 200
    exported_path = export_storage.export_path(job_id, export_id, "docx")
    reparsed = DocxParser().parse(
        exported_path,
        document_id=uuid4(),
        source_name="modified_document.docx",
    )
    assert [block.text for block in reparsed.blocks] == ["核验示例正文"]
    stored = _load_export(db_session_factory, export_id)
    assert stored.status == ExportStatus.COMPLETED
    assert len(stored.warnings) == 1
    assert "unsafe_docx_run_boundary" in stored.warnings[0]
    assert str(unsafe_issue.issue_id) in stored.warnings[0]


def test_html_report_task_includes_checker_failures_and_replacement_warnings(
    client,
    celery_eager,
    db_session: Session,
    db_session_factory: sessionmaker[Session],
    export_storage: JobStorage,
) -> None:
    issue = _build_issue(
        document_id=uuid4(),
        block_id="p-000001",
        original="原始",
        suggestion=None,
        start=0,
        end=2,
        page=1,
    )
    job_id = _seed_analyzed_job(
        db_session,
        file_type=FileType.PDF,
        document=_simple_document(
            document_id=issue.document_id,
            file_type=FileType.PDF,
            text="原始正文",
        ),
        issues=[issue],
        failures={
            CheckCategory.SECURITY: CheckerFailure(
                code="checker_failed",
                message="安全分类检查失败。",
            )
        },
    )
    _apply_decision(db_session, job_id, issue, DecisionAction.ACCEPTED)

    created = client.post(
        f"/api/v1/jobs/{job_id}/exports",
        json={"type": "html_report"},
    )
    export_id = UUID(created.json()["export_id"])
    download = client.get(f"/api/v1/jobs/{job_id}/exports/{export_id}/download")

    assert created.status_code == 202
    assert download.status_code == 200
    html = download.content.decode("utf-8")
    assert "checker_failed" in html
    assert "安全分类检查失败。" in html
    assert "missing_replacement_value" in html
    stored = _load_export(db_session_factory, export_id)
    assert len(stored.warnings) == 1
    assert "missing_replacement_value" in stored.warnings[0]


@pytest.mark.skipif(os.name == "nt", reason="WeasyPrint native runtime is provided by Docker")
def test_pdf_report_task_generates_pdf_for_pdf_job(
    client,
    celery_eager,
    db_session: Session,
    export_storage: JobStorage,
) -> None:
    job_id = _seed_analyzed_job(
        db_session,
        file_type=FileType.PDF,
        document=_simple_document(
            document_id=uuid4(),
            file_type=FileType.PDF,
            text="报告正文",
        ),
        issues=[],
        failures={},
    )

    created = client.post(
        f"/api/v1/jobs/{job_id}/exports",
        json={"type": "pdf_report"},
    )
    export_id = UUID(created.json()["export_id"])
    download = client.get(f"/api/v1/jobs/{job_id}/exports/{export_id}/download")

    assert created.status_code == 202
    assert download.status_code == 200
    assert download.content.startswith(b"%PDF")
    assert export_storage.export_path(job_id, export_id, "pdf").is_file()


def test_transient_task_failure_retries_and_completes_without_terminal_regression(
    celery_eager,
    db_session: Session,
    db_session_factory: sessionmaker[Session],
    export_storage: JobStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from text_verification.workers import export_tasks

    job_id, _issue = _seed_reviewed_txt_job(db_session, export_storage)
    export = ExportRepository(db_session).create(
        job_id,
        export_tasks.ExportType.MODIFIED_DOCUMENT,
        "txt",
    )
    db_session.commit()
    real_export = TxtExporter.export
    attempts = 0

    def flaky_export(self, document, plan, target):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("transient write failure")
        return real_export(self, document, plan, target)

    monkeypatch.setattr(TxtExporter, "export", flaky_export)

    result = export_tasks.process_export.delay(str(export.export_id))

    assert result.successful()
    assert attempts == 2
    stored = _load_export(db_session_factory, export.export_id)
    assert stored.status == ExportStatus.COMPLETED


def test_repeat_delivery_keeps_completed_export_terminal(
    celery_eager,
    db_session: Session,
    db_session_factory: sessionmaker[Session],
    export_storage: JobStorage,
) -> None:
    from text_verification.workers import export_tasks

    job_id, _issue = _seed_reviewed_txt_job(db_session, export_storage)
    export = ExportRepository(db_session).create(
        job_id,
        export_tasks.ExportType.MODIFIED_DOCUMENT,
        "txt",
    )
    db_session.commit()

    first_result = export_tasks.process_export.delay(str(export.export_id))
    first_stored = _load_export(db_session_factory, export.export_id)
    second_result = export_tasks.process_export.delay(str(export.export_id))
    second_stored = _load_export(db_session_factory, export.export_id)

    assert export_tasks.process_export.name == "text_verification.process_export"
    assert first_result.successful()
    assert second_result.successful()
    assert first_stored.status == ExportStatus.COMPLETED
    assert second_stored.status == ExportStatus.COMPLETED
    assert second_stored.updated_at == first_stored.updated_at
    assert export_storage.export_path(job_id, export.export_id, "txt").read_text(
        encoding="utf-8"
    ) == "修改后的正文\n"


def test_exhausted_task_failure_is_safe_and_repeat_delivery_stays_failed(
    celery_eager,
    db_session: Session,
    db_session_factory: sessionmaker[Session],
    export_storage: JobStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from text_verification.workers import export_tasks

    job_id, _issue = _seed_reviewed_txt_job(db_session, export_storage)
    export = ExportRepository(db_session).create(
        job_id,
        export_tasks.ExportType.MODIFIED_DOCUMENT,
        "txt",
    )
    db_session.commit()
    attempts = 0

    def failing_export(self, document, plan, target):
        nonlocal attempts
        attempts += 1
        raise RuntimeError(r"internal failure at C:\secret\jobs\artifact.txt")

    monkeypatch.setattr(TxtExporter, "export", failing_export)

    first_result = export_tasks.process_export.delay(str(export.export_id))
    first_stored = _load_export(db_session_factory, export.export_id)
    second_result = export_tasks.process_export.delay(str(export.export_id))
    second_stored = _load_export(db_session_factory, export.export_id)

    assert first_result.failed()
    assert second_result.failed()
    assert attempts == export_tasks.PROCESS_EXPORT_MAX_RETRIES + 1
    assert first_stored.status == ExportStatus.FAILED
    assert first_stored.error_code == "export_failed"
    assert first_stored.error_message == "导出失败，请稍后重试。"
    assert "secret" not in first_stored.error_message
    assert second_stored.status == ExportStatus.FAILED
    assert second_stored.updated_at == first_stored.updated_at
    assert not export_storage.export_path(job_id, export.export_id, "txt").exists()


def test_expected_export_error_persists_public_code_and_task_result_is_failed(
    celery_eager,
    db_session: Session,
    db_session_factory: sessionmaker[Session],
    export_storage: JobStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from text_verification.workers import export_tasks

    job_id, _issue = _seed_reviewed_txt_job(db_session, export_storage)
    export = ExportRepository(db_session).create(
        job_id,
        export_tasks.ExportType.MODIFIED_DOCUMENT,
        "txt",
    )
    db_session.commit()

    def failing_export(self, document, plan, target):
        raise ExportError("txt_export_failed", "无法导出 TXT 文件。")

    monkeypatch.setattr(TxtExporter, "export", failing_export)

    result = export_tasks.process_export.delay(str(export.export_id))

    assert result.failed()
    stored = _load_export(db_session_factory, export.export_id)
    assert stored.status == ExportStatus.FAILED
    assert stored.error_code == "txt_export_failed"
    assert stored.error_message == "无法导出 TXT 文件。"


def _seed_reviewed_txt_job(
    session: Session,
    storage: JobStorage,
) -> tuple[UUID, Issue]:
    job_id = _seed_empty_job(
        session,
        file_type=FileType.TXT,
        status=JobStatus.COMPLETED,
    )
    stored = storage.save_bytes(job_id, "sample.txt", "原始正文".encode())
    document = TxtParser().parse(
        stored.path,
        document_id=uuid4(),
        source_name="sample.txt",
    )
    issue = _build_issue(
        document_id=document.document_id,
        block_id=document.blocks[0].block_id,
        original="原始",
        suggestion="修改后的",
        start=0,
        end=2,
    )
    AnalysisRepository(session).replace_analysis(job_id, document, [issue], {})
    session.commit()
    _apply_decision(session, job_id, issue, DecisionAction.ACCEPTED)
    return job_id, issue


def _seed_reviewed_docx_job(
    session: Session,
    storage: JobStorage,
) -> tuple[UUID, Issue]:
    job_id = _seed_empty_job(
        session,
        file_type=FileType.DOCX,
        status=JobStatus.COMPLETED,
    )
    source = WordDocument()
    paragraph = source.add_paragraph()
    paragraph.add_run("核验")
    paragraph.add_run("示例")
    paragraph.add_run("文本")
    payload = BytesIO()
    source.save(payload)
    stored = storage.save_bytes(job_id, "sample.docx", payload.getvalue())
    document = DocxParser().parse(
        stored.path,
        document_id=uuid4(),
        source_name="sample.docx",
    )
    unsafe_issue = _build_issue(
        document_id=document.document_id,
        block_id=document.blocks[0].block_id,
        original="验示",
        suggestion="审查",
        start=1,
        end=3,
    )
    safe_issue = _build_issue(
        document_id=document.document_id,
        block_id=document.blocks[0].block_id,
        original="文本",
        suggestion="正文",
        start=4,
        end=6,
    )
    AnalysisRepository(session).replace_analysis(
        job_id,
        document,
        [unsafe_issue, safe_issue],
        {},
    )
    session.commit()
    _apply_decision(session, job_id, unsafe_issue, DecisionAction.ACCEPTED)
    _apply_decision(session, job_id, safe_issue, DecisionAction.ACCEPTED)
    return job_id, unsafe_issue


def _seed_analyzed_job(
    session: Session,
    *,
    file_type: FileType,
    document: DocumentModel,
    issues: list[Issue],
    failures: dict[CheckCategory, CheckerFailure],
) -> UUID:
    job_id = _seed_empty_job(
        session,
        file_type=file_type,
        status=JobStatus.COMPLETED if not failures else JobStatus.PARTIAL,
    )
    AnalysisRepository(session).replace_analysis(job_id, document, issues, failures)
    session.commit()
    return job_id


def _seed_empty_job(
    session: Session,
    *,
    file_type: FileType,
    status: JobStatus,
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
        expires_at=now + timedelta(hours=1),
    )
    if status != JobStatus.QUEUED:
        repository.transition(
            job_id,
            status,
            100,
            "处理完成",
        )
    repository.commit()
    return job_id


def _apply_decision(
    session: Session,
    job_id: UUID,
    issue: Issue,
    action: DecisionAction,
) -> None:
    outcome = DecisionRepository(session).apply(
        job_id,
        DecisionCommand(
            issue_id=issue.issue_id,
            issue_version=1,
            action=action,
        ),
    )
    assert outcome.decision is not None
    session.commit()


def _simple_document(
    *,
    document_id: UUID,
    file_type: FileType,
    text: str,
) -> DocumentModel:
    return DocumentModel(
        document_id=document_id,
        file_type=file_type,
        source_name=f"sample.{file_type.value}",
        version=1,
        blocks=[
            {
                "block_id": "p-000001",
                "kind": "paragraph",
                "text": text,
                "page": 1 if file_type == FileType.PDF else None,
                "paragraph_index": 0,
                "parent_id": None,
                "style": {},
                "source_locator": {"paragraph_index": 0},
            }
        ],
        metadata={},
    )


def _build_issue(
    *,
    document_id: UUID,
    block_id: str,
    original: str,
    suggestion: str | None,
    start: int,
    end: int,
    page: int | None = None,
) -> Issue:
    return Issue(
        issue_id=uuid4(),
        document_id=document_id,
        block_id=block_id,
        page=page,
        start=start,
        end=end,
        original=original,
        suggestion=suggestion,
        alternatives=[] if suggestion is None else [suggestion],
        type="literal",
        severity=IssueSeverity.WARNING,
        layer=CheckCategory.CHARACTER.value,
        message="命中规则。",
        rule_id="character-001",
        source="test",
        source_version="1",
        confidence=1.0,
        auto_fixable=suggestion is not None,
        context=original,
    )


def _load_export(
    session_factory: sessionmaker[Session],
    export_id: UUID,
):
    session = session_factory()
    try:
        stored = ExportRepository(session).get(export_id)
        assert stored is not None
        return stored
    finally:
        session.close()
