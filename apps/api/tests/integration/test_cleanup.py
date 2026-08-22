from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from text_verification.checkers.models import CHECK_CATEGORY_ORDER, CheckScenario
from text_verification.domain.documents import DocumentModel, FileType
from text_verification.domain.exports import (
    ExportIssueSummarySnapshot,
    ExportSnapshot,
    ExportType,
)
from text_verification.domain.jobs import JobEvent, JobRead, JobStatus
from text_verification.infrastructure.export_repository import ExportRepository
from text_verification.infrastructure.orm import ExportRow, JobRow
from text_verification.infrastructure.repositories import JobRepository
from text_verification.infrastructure.storage import JobStorage


class InMemoryCleanupRepository:
    def __init__(self) -> None:
        self._jobs: dict[UUID, JobRead] = {}
        self._events: dict[UUID, list[JobEvent]] = {}

    def create_job(
        self,
        *,
        status: JobStatus,
        expires_at: datetime,
        source_name: str = "sample.txt",
    ) -> JobRead:
        job_id = uuid4()
        created_at = expires_at - timedelta(hours=1)
        progress = 100 if status == JobStatus.COMPLETED else 0
        job = JobRead(
            job_id=job_id,
            source_name=source_name,
            file_type=FileType.TXT,
            size_bytes=8,
            status=status,
            progress=progress,
            created_at=created_at,
            expires_at=expires_at,
        )
        self._jobs[job_id] = job
        self._events[job_id] = [
            JobEvent(
                sequence=1,
                status=status,
                progress=progress,
                message="种子事件",
                created_at=created_at,
            )
        ]
        return job

    def get_job(self, job_id: UUID) -> JobRead | None:
        return self._jobs.get(job_id)

    def list_job_ids(self) -> set[UUID]:
        return set(self._jobs)

    def expire_jobs_before(self, cutoff: datetime) -> list[UUID]:
        expired_job_ids: list[UUID] = []
        for job_id, job in sorted(self._jobs.items(), key=lambda item: str(item[0])):
            if job.expires_at > cutoff:
                continue
            if job.status != JobStatus.EXPIRED:
                self._jobs[job_id] = job.model_copy(update={"status": JobStatus.EXPIRED})
                self._events[job_id].append(
                    JobEvent(
                        sequence=len(self._events[job_id]) + 1,
                        status=JobStatus.EXPIRED,
                        progress=job.progress,
                        message="作业已过期",
                        created_at=cutoff,
                    )
                )
            expired_job_ids.append(job_id)
        return expired_job_ids

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


@dataclass
class FakeSession:
    closed: bool = False

    def close(self) -> None:
        self.closed = True


@dataclass
class SessionFactorySpy:
    sessions: list[FakeSession]

    def __call__(self) -> FakeSession:
        session = FakeSession()
        self.sessions.append(session)
        return session


@pytest.fixture
def repository() -> InMemoryCleanupRepository:
    return InMemoryCleanupRepository()


@pytest.fixture
def storage(tmp_path) -> JobStorage:
    root = tmp_path / "jobs"
    root.mkdir()
    return JobStorage(root, max_upload_bytes=25 * 1024 * 1024)


@pytest.fixture(autouse=True)
def cleanup_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    repository: InMemoryCleanupRepository,
    storage: JobStorage,
) -> SessionFactorySpy:
    from text_verification.workers import tasks as worker_tasks

    session_factory = SessionFactorySpy([])
    monkeypatch.setattr(worker_tasks, "SESSION_FACTORY_PROVIDER", lambda: session_factory)
    monkeypatch.setattr(worker_tasks, "REPOSITORY_FACTORY", lambda session: repository)
    monkeypatch.setattr(worker_tasks, "STORAGE_FACTORY", lambda: storage)
    monkeypatch.setattr(
        worker_tasks,
        "get_settings",
        lambda: SimpleNamespace(job_retention_hours=24),
    )
    return session_factory


@pytest.fixture
def expired_job(repository: InMemoryCleanupRepository, storage: JobStorage) -> JobRead:
    job = repository.create_job(
        status=JobStatus.COMPLETED,
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    storage.save_bytes(job.job_id, "sample.txt", b"content")
    return job


def test_cleanup_expires_database_job_and_deletes_exact_directory(
    repository: InMemoryCleanupRepository,
    storage: JobStorage,
    expired_job: JobRead,
) -> None:
    from text_verification.workers.tasks import cleanup_expired_jobs

    live_job = repository.create_job(
        status=JobStatus.COMPLETED,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        source_name="live.txt",
    )
    storage.save_bytes(live_job.job_id, "live.txt", b"live")
    export_id = uuid4()
    storage.export_path(expired_job.job_id, export_id, "txt").write_text(
        "expired export",
        encoding="utf-8",
    )

    deleted_job_ids = cleanup_expired_jobs()

    assert repository.get_job(expired_job.job_id) is not None
    assert repository.get_job(expired_job.job_id).status == JobStatus.EXPIRED
    assert not storage.job_directory(expired_job.job_id).exists()
    assert storage.job_directory(live_job.job_id).exists()
    assert deleted_job_ids == [str(expired_job.job_id)]


def test_deleting_job_cascades_export_rows(db_session: Session) -> None:
    now = datetime.now(UTC)
    job_id = uuid4()
    job_repository = JobRepository(db_session)
    job_repository.create_job(
        job_id=job_id,
        source_name="sample.txt",
        file_type=FileType.TXT.value,
        size_bytes=8,
        storage_key=str(job_id),
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )
    export = ExportRepository(db_session).create(
        job_id,
        ExportType.MODIFIED_DOCUMENT,
        "txt",
        snapshot=ExportSnapshot(
            schema_version=2,
            document_version_id=UUID("00000000-0000-0000-0000-000000000100"),
            decision_snapshot_sha256="0" * 64,
            captured_at=now,
            source_name="sample.txt",
            source_type=FileType.TXT,
            source_size_bytes=8,
            source_sha256=None,
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
                file_type=FileType.TXT,
                source_name="sample.txt",
                version=1,
                blocks=[],
                metadata={},
            ),
            issues=[],
            preflight_warnings=[],
        ),
    )
    db_session.commit()

    db_session.execute(delete(JobRow).where(JobRow.job_id == job_id))
    db_session.commit()

    assert db_session.get(ExportRow, export.export_id) is None


def test_cleanup_retries_storage_deletion_for_already_expired_jobs(
    repository: InMemoryCleanupRepository,
    storage: JobStorage,
    expired_job: JobRead,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from text_verification.workers.tasks import cleanup_expired_jobs

    real_delete_job = storage.delete_job
    delete_attempts = 0

    def flaky_delete_job(job_id: UUID) -> None:
        nonlocal delete_attempts
        delete_attempts += 1
        if delete_attempts == 1:
            raise PermissionError("locked")
        real_delete_job(job_id)

    monkeypatch.setattr(storage, "delete_job", flaky_delete_job)

    with caplog.at_level(logging.WARNING, logger="text_verification.workers.tasks"):
        first_deleted_job_ids = cleanup_expired_jobs()
        second_deleted_job_ids = cleanup_expired_jobs()

    assert repository.get_job(expired_job.job_id) is not None
    assert repository.get_job(expired_job.job_id).status == JobStatus.EXPIRED
    assert first_deleted_job_ids == []
    assert second_deleted_job_ids == [str(expired_job.job_id)]
    assert not storage.job_directory(expired_job.job_id).exists()
    assert delete_attempts == 2
    assert [record.getMessage() for record in caplog.records] == [
        "cleanup_expired_job_delete_failed"
    ]
    assert caplog.records[0].job_id == str(expired_job.job_id)
    assert caplog.records[0].error_type == "PermissionError"


def test_cleanup_sweeps_only_stale_unpersisted_directories(
    repository: InMemoryCleanupRepository,
    storage: JobStorage,
) -> None:
    from text_verification.workers.tasks import cleanup_expired_jobs

    stale_orphan = uuid4()
    fresh_orphan = uuid4()
    persisted = repository.create_job(
        status=JobStatus.COMPLETED,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    storage.save_bytes(stale_orphan, "stale.txt", b"stale")
    storage.save_bytes(fresh_orphan, "fresh.txt", b"fresh")
    storage.save_bytes(persisted.job_id, "persisted.txt", b"persisted")
    stale_timestamp = (datetime.now(UTC) - timedelta(hours=25)).timestamp()
    os.utime(storage.job_directory(stale_orphan), (stale_timestamp, stale_timestamp))
    os.utime(storage.job_directory(persisted.job_id), (stale_timestamp, stale_timestamp))

    deleted_job_ids = cleanup_expired_jobs()

    assert deleted_job_ids == [str(stale_orphan)]
    assert not storage.job_directory(stale_orphan).exists()
    assert storage.job_directory(fresh_orphan).exists()
    assert storage.job_directory(persisted.job_id).exists()


def test_cleanup_is_scheduled_hourly() -> None:
    from text_verification.workers.celery_app import celery_app

    assert celery_app.conf.beat_schedule["cleanup-expired-jobs-hourly"] == {
        "task": "text_verification.cleanup_expired_jobs",
        "schedule": 3600.0,
    }
