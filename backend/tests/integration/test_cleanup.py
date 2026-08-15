from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from text_verification.domain.documents import FileType
from text_verification.domain.jobs import JobEvent, JobRead, JobStatus
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

    deleted_job_ids = cleanup_expired_jobs()

    assert repository.get_job(expired_job.job_id) is not None
    assert repository.get_job(expired_job.job_id).status == JobStatus.EXPIRED
    assert not storage.job_directory(expired_job.job_id).exists()
    assert storage.job_directory(live_job.job_id).exists()
    assert deleted_job_ids == [str(expired_job.job_id)]


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


def test_cleanup_is_scheduled_hourly() -> None:
    from text_verification.workers.celery_app import celery_app

    assert celery_app.conf.beat_schedule["cleanup-expired-jobs-hourly"] == {
        "task": "text_verification.cleanup_expired_jobs",
        "schedule": 3600.0,
    }
