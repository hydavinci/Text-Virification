from __future__ import annotations

from datetime import UTC, datetime, timedelta
from importlib import import_module
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from text_verification.checkers.models import CHECK_CATEGORY_ORDER, CheckScenario
from text_verification.domain.documents import DocumentModel, FileType
from text_verification.domain.exports import (
    ExportIssueSummarySnapshot,
    ExportSnapshot,
    ExportWarning,
)
from text_verification.infrastructure.repositories import JobRepository


@pytest.fixture
def postgres_session(db_session: Session) -> Session:
    return db_session


@pytest.mark.parametrize(
    ("export_type_name", "extension", "expected_file_name"),
    [
        ("MODIFIED_DOCUMENT", "txt", "modified_document.txt"),
        ("MODIFIED_DOCUMENT", "docx", "modified_document.docx"),
        ("HTML_REPORT", "html", "report.html"),
        ("PDF_REPORT", "pdf", "report.pdf"),
    ],
    ids=["modified-txt", "modified-docx", "html-report", "pdf-report"],
)
def test_export_lifecycle_round_trip(
    postgres_session: Session,
    export_type_name: str,
    extension: str,
    expected_file_name: str,
) -> None:
    ExportType, ExportStatus, ExportRepository, _ = _export_symbols()
    job_id, expires_at = seed_job(postgres_session)
    repository = ExportRepository(postgres_session)
    export_type = getattr(ExportType, export_type_name)
    snapshot = build_snapshot(
        file_type=FileType(extension) if extension in {"txt", "docx"} else FileType.TXT
    )
    warning = ExportWarning(
        code="unsafe_docx_run_boundary",
        message="请手动修改后重新导出。",
        issue_id=UUID("00000000-0000-0000-0000-000000000001"),
        block_id="p-000001",
    )

    created = repository.create(
        job_id,
        export_type,
        extension,
        snapshot=snapshot,
    )
    processing = repository.mark_processing(created.export_id)
    completed = repository.mark_completed(
        created.export_id,
        warnings=[warning],
    )
    postgres_session.commit()

    stored = repository.get(created.export_id)

    assert created.status == ExportStatus.QUEUED
    assert processing.status == ExportStatus.PROCESSING
    assert completed.status == ExportStatus.COMPLETED
    assert stored is not None
    assert stored.export_id == created.export_id
    assert stored.job_id == job_id
    assert stored.export_type == export_type
    assert stored.status == ExportStatus.COMPLETED
    assert stored.file_name == expected_file_name
    assert stored.storage_key is not None
    assert str(job_id) in stored.storage_key
    assert stored.storage_key.endswith(f"{created.export_id}.{extension}")
    assert stored.warnings == [warning]
    assert stored.snapshot == snapshot
    assert stored.error_code is None
    assert stored.error_message is None
    assert stored.expires_at == expires_at


@pytest.mark.parametrize(
    ("terminal_method", "terminal_kwargs"),
    [
        ("mark_completed", {"warnings": []}),
        (
            "mark_failed",
            {
                "error_code": "render_failed",
                "error_message": "HTML rendering failed.",
            },
        ),
    ],
    ids=["completed", "failed"],
)
def test_terminal_export_states_reject_later_transitions(
    postgres_session: Session,
    terminal_method: str,
    terminal_kwargs: dict[str, Any],
) -> None:
    ExportType, _, ExportRepository, TerminalExportStateError = _export_symbols()
    job_id, _ = seed_job(postgres_session)
    repository = ExportRepository(postgres_session)
    export = repository.create(
        job_id,
        ExportType.PDF_REPORT,
        "pdf",
        snapshot=build_snapshot(file_type=FileType.TXT),
    )

    getattr(repository, terminal_method)(export.export_id, **terminal_kwargs)

    with pytest.raises(TerminalExportStateError, match="terminal"):
        repository.mark_processing(export.export_id)


@pytest.mark.parametrize(
    ("export_type_name", "extension"),
    [
        ("MODIFIED_DOCUMENT", "html"),
        ("MODIFIED_DOCUMENT", "pdf"),
        ("HTML_REPORT", "pdf"),
        ("PDF_REPORT", "html"),
    ],
    ids=[
        "modified-with-html",
        "modified-with-pdf",
        "html-report-with-pdf",
        "pdf-report-with-html",
    ],
)
def test_create_rejects_mismatched_export_type_and_extension(
    postgres_session: Session,
    export_type_name: str,
    extension: str,
) -> None:
    ExportType, _, ExportRepository, _ = _export_symbols()
    job_id, _ = seed_job(postgres_session)
    export_type = getattr(ExportType, export_type_name)

    with pytest.raises(ValueError, match="supports extension"):
        ExportRepository(postgres_session).create(
            job_id,
            export_type,
            extension,
            snapshot=build_snapshot(file_type=FileType.TXT),
        )


@pytest.mark.parametrize("extension", ["../report.html", "zip", "html.exe"])
def test_create_rejects_path_like_or_unsupported_extension(
    postgres_session: Session,
    extension: str,
) -> None:
    ExportType, _, ExportRepository, _ = _export_symbols()
    job_id, _ = seed_job(postgres_session)

    with pytest.raises(ValueError, match="Unsupported export extension"):
        ExportRepository(postgres_session).create(
            job_id,
            ExportType.HTML_REPORT,
            extension,
            snapshot=build_snapshot(file_type=FileType.TXT),
        )


def _export_symbols() -> tuple[Any, Any, Any, Any]:
    try:
        domain_module = import_module("text_verification.domain.exports")
        repository_module = import_module("text_verification.infrastructure.export_repository")
    except ModuleNotFoundError as error:
        pytest.fail(f"Export persistence is not implemented yet: {error}")

    try:
        return (
            domain_module.ExportType,
            domain_module.ExportStatus,
            repository_module.ExportRepository,
            domain_module.TerminalExportStateError,
        )
    except AttributeError as error:
        pytest.fail(f"Export persistence is not implemented yet: {error}")


def seed_job(postgres_session: Session) -> tuple[UUID, datetime]:
    now = datetime.now(UTC)
    job_id = uuid4()
    expires_at = now + timedelta(hours=1)
    repository = JobRepository(postgres_session)
    repository.create_job(
        job_id=job_id,
        source_name="analysis.txt",
        file_type=FileType.TXT.value,
        size_bytes=16,
        storage_key=str(job_id),
        created_at=now,
        expires_at=expires_at,
    )
    repository.commit()
    return job_id, expires_at


def build_snapshot(*, file_type: FileType) -> ExportSnapshot:
    source_name = f"analysis.{file_type.value}"
    return ExportSnapshot(
        captured_at=datetime.now(UTC),
        source_name=source_name,
        source_type=file_type,
        source_size_bytes=16,
        source_sha256="0" * 64 if file_type == FileType.DOCX else None,
        scenario=CheckScenario.GENERAL,
        enabled_categories=list(CHECK_CATEGORY_ORDER),
        completed_categories=list(CHECK_CATEGORY_ORDER),
        checker_failures=[],
        summary=ExportIssueSummarySnapshot(
            total=0,
            by_category={},
            by_severity={},
            by_decision={},
        ),
        document=DocumentModel(
            document_id=uuid4(),
            file_type=file_type,
            source_name=source_name,
            version=1,
            blocks=[],
            metadata={},
        ),
        issues=[],
        preflight_warnings=[],
    )
