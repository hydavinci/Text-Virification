from __future__ import annotations

from datetime import UTC, datetime, timedelta
from importlib import import_module
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from text_verification.domain.documents import FileType
from text_verification.infrastructure.repositories import JobRepository


@pytest.fixture
def postgres_session(db_session: Session) -> Session:
    return db_session


def test_export_lifecycle_round_trip(postgres_session: Session) -> None:
    ExportType, ExportStatus, ExportRepository, _ = _export_symbols()
    job_id, expires_at = seed_job(postgres_session)
    repository = ExportRepository(postgres_session)

    created = repository.create(job_id, ExportType.HTML_REPORT, "report.html")
    processing = repository.mark_processing(created.export_id)
    completed = repository.mark_completed(
        created.export_id,
        warnings=["1 项修改未自动应用"],
    )
    postgres_session.commit()

    stored = repository.get(created.export_id)

    assert created.status == ExportStatus.QUEUED
    assert processing.status == ExportStatus.PROCESSING
    assert completed.status == ExportStatus.COMPLETED
    assert stored is not None
    assert stored.export_id == created.export_id
    assert stored.job_id == job_id
    assert stored.export_type == ExportType.HTML_REPORT
    assert stored.status == ExportStatus.COMPLETED
    assert stored.file_name == "report.html"
    assert stored.storage_key is not None
    assert str(job_id) in stored.storage_key
    assert stored.storage_key.endswith(f"{created.export_id}.html")
    assert stored.warnings == ["1 项修改未自动应用"]
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
    export = repository.create(job_id, ExportType.PDF_REPORT, "report.pdf")

    getattr(repository, terminal_method)(export.export_id, **terminal_kwargs)

    with pytest.raises(TerminalExportStateError, match="terminal"):
        repository.mark_processing(export.export_id)


def test_create_rejects_path_like_file_name(postgres_session: Session) -> None:
    ExportType, _, ExportRepository, _ = _export_symbols()
    job_id, _ = seed_job(postgres_session)

    with pytest.raises(ValueError, match="file_name"):
        ExportRepository(postgres_session).create(
            job_id,
            ExportType.HTML_REPORT,
            "../report.html",
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
