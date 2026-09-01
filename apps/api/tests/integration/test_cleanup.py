from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from text_verification.compatibility.storage import CompatibilityStorage
from text_verification.domain.documents import FileType
from text_verification.domain.jobs import JobEvent, JobRead, JobStatus
from text_verification.infrastructure.storage import (
    JobStorage,
    build_artifact_storage_key,
)


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


class InMemoryCleanupVerificationRepository:
    def __init__(self) -> None:
        self.deleted_job_ids: list[UUID] = []
        self.artifact_keys: dict[UUID, tuple[str, ...]] = {}

    def list_artifact_storage_keys(self, job_id: UUID) -> tuple[str, ...]:
        return self.artifact_keys.get(job_id, ())

    def list_all_artifact_storage_keys(self) -> tuple[str, ...]:
        return tuple(
            storage_key
            for keys in self.artifact_keys.values()
            for storage_key in keys
        )

    def list_stale_pending_artifacts(self, older_than: datetime) -> tuple[object, ...]:
        del older_than
        return ()

    def delete_unreferenced_artifact(
        self,
        *,
        job_id: UUID,
        artifact_id: UUID,
        file_type: FileType,
        storage_key: str,
        candidate_storage_key: str,
        delete_path,
    ) -> bool:
        del artifact_id, file_type, storage_key
        if candidate_storage_key in self.list_all_artifact_storage_keys():
            return False
        return delete_path(not self.artifact_keys.get(job_id))

    def delete_results_for_jobs(self, job_ids: list[UUID]) -> None:
        self.deleted_job_ids.extend(job_ids)
        for job_id in job_ids:
            self.artifact_keys.pop(job_id, None)

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


@dataclass(frozen=True)
class ArtifactFixture:
    storage_key: str
    path: Path


def _publish_artifact_fixture(
    storage: JobStorage,
    job_id: UUID,
    artifact_id: UUID,
    data: bytes,
) -> ArtifactFixture:
    storage_key = build_artifact_storage_key(job_id, artifact_id, FileType.TXT)
    with storage.publish_verified_artifact(
        job_id,
        artifact_id,
        storage_key,
        FileType.TXT,
        data,
    ) as handle:
        return ArtifactFixture(storage_key=handle.storage_key, path=handle.path)


@pytest.fixture
def repository() -> InMemoryCleanupRepository:
    return InMemoryCleanupRepository()


@pytest.fixture
def storage(tmp_path) -> JobStorage:
    root = tmp_path / "jobs"
    root.mkdir()
    return JobStorage(root, max_upload_bytes=25 * 1024 * 1024)


@pytest.fixture
def compatibility_storage(tmp_path: Path) -> CompatibilityStorage:
    return CompatibilityStorage(tmp_path / "jobs", max_upload_bytes=25 * 1024 * 1024)


@pytest.fixture
def verification_repository() -> InMemoryCleanupVerificationRepository:
    return InMemoryCleanupVerificationRepository()


@pytest.fixture(autouse=True)
def cleanup_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    repository: InMemoryCleanupRepository,
    verification_repository: InMemoryCleanupVerificationRepository,
    storage: JobStorage,
    compatibility_storage: CompatibilityStorage,
) -> SessionFactorySpy:
    from text_verification.workers import tasks as worker_tasks

    session_factory = SessionFactorySpy([])
    monkeypatch.setattr(worker_tasks, "SESSION_FACTORY_PROVIDER", lambda: session_factory)
    monkeypatch.setattr(worker_tasks, "REPOSITORY_FACTORY", lambda session: repository)
    monkeypatch.setattr(
        worker_tasks,
        "VERIFICATION_REPOSITORY_FACTORY",
        lambda session: verification_repository,
    )
    monkeypatch.setattr(worker_tasks, "STORAGE_FACTORY", lambda: storage)
    monkeypatch.setattr(
        worker_tasks,
        "COMPATIBILITY_STORAGE_FACTORY",
        lambda: compatibility_storage,
    )
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


def test_cleanup_deletes_recorded_export_outside_job_directory_before_aggregate(
    repository: InMemoryCleanupRepository,
    verification_repository: InMemoryCleanupVerificationRepository,
    storage: JobStorage,
    expired_job: JobRead,
) -> None:
    from text_verification.workers.tasks import cleanup_expired_jobs

    storage_key = f"artifacts/{expired_job.job_id}/{uuid4()}.txt"
    export_path = storage._root / storage_key
    export_path.parent.mkdir(parents=True)
    export_path.write_text("reviewed", encoding="utf-8")
    verification_repository.artifact_keys[expired_job.job_id] = (storage_key,)

    deleted_job_ids = cleanup_expired_jobs()

    assert deleted_job_ids == [str(expired_job.job_id)]
    assert not export_path.exists()
    assert not storage.job_directory(expired_job.job_id).exists()
    assert verification_repository.deleted_job_ids == [expired_job.job_id]


def test_cleanup_rejects_artifact_traversal_and_keeps_aggregate_for_retry(
    verification_repository: InMemoryCleanupVerificationRepository,
    storage: JobStorage,
    expired_job: JobRead,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from text_verification.workers.tasks import cleanup_expired_jobs

    outside = tmp_path / "outside.txt"
    outside.write_text("keep", encoding="utf-8")
    verification_repository.artifact_keys[expired_job.job_id] = ("../outside.txt",)

    with caplog.at_level(logging.WARNING, logger="text_verification.workers.tasks"):
        deleted_job_ids = cleanup_expired_jobs()

    assert deleted_job_ids == []
    assert outside.read_text(encoding="utf-8") == "keep"
    assert storage.job_directory(expired_job.job_id).exists()
    assert verification_repository.deleted_job_ids == []
    assert [record.getMessage() for record in caplog.records] == [
        "cleanup_expired_job_delete_failed"
    ]


def test_cleanup_rejects_cross_job_artifact_and_keeps_metadata(
    verification_repository: InMemoryCleanupVerificationRepository,
    storage: JobStorage,
    expired_job: JobRead,
    repository: InMemoryCleanupRepository,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from text_verification.workers.tasks import cleanup_expired_jobs

    other_job = repository.create_job(
        status=JobStatus.COMPLETED,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    storage_key = f"artifacts/{other_job.job_id}/{uuid4()}.txt"
    artifact_path = storage._root / storage_key
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text("keep", encoding="utf-8")
    verification_repository.artifact_keys[expired_job.job_id] = (storage_key,)

    with caplog.at_level(logging.WARNING, logger="text_verification.workers.tasks"):
        deleted_job_ids = cleanup_expired_jobs()

    assert deleted_job_ids == []
    assert artifact_path.read_text(encoding="utf-8") == "keep"
    assert storage.job_directory(expired_job.job_id).exists()
    assert verification_repository.artifact_keys[expired_job.job_id] == (storage_key,)
    assert verification_repository.deleted_job_ids == []
    assert [record.getMessage() for record in caplog.records] == [
        "cleanup_expired_job_delete_failed"
    ]


def test_cleanup_partial_artifact_failure_retries_before_deleting_aggregate(
    verification_repository: InMemoryCleanupVerificationRepository,
    storage: JobStorage,
    expired_job: JobRead,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from text_verification.workers.tasks import cleanup_expired_jobs

    first_key = f"artifacts/{expired_job.job_id}/{uuid4()}-a.txt"
    second_key = f"artifacts/{expired_job.job_id}/{uuid4()}-b.txt"
    first_path = storage._root / first_key
    second_path = storage._root / second_key
    first_path.parent.mkdir(parents=True)
    first_path.write_text("first", encoding="utf-8")
    second_path.write_text("second", encoding="utf-8")
    verification_repository.artifact_keys[expired_job.job_id] = (
        first_key,
        second_key,
    )
    real_delete_artifact = storage.delete_artifact
    second_attempts = 0

    def flaky_delete_artifact(job_id: UUID, storage_key: str) -> bool:
        nonlocal second_attempts
        if storage_key == second_key:
            second_attempts += 1
            if second_attempts == 1:
                raise PermissionError("locked")
        return real_delete_artifact(job_id, storage_key)

    monkeypatch.setattr(storage, "delete_artifact", flaky_delete_artifact)

    assert cleanup_expired_jobs() == []
    assert not first_path.exists()
    assert second_path.exists()
    assert storage.job_directory(expired_job.job_id).exists()
    assert verification_repository.deleted_job_ids == []

    assert cleanup_expired_jobs() == [str(expired_job.job_id)]
    assert not second_path.exists()
    assert not storage.job_directory(expired_job.job_id).exists()
    assert verification_repository.deleted_job_ids == [expired_job.job_id]
    assert second_attempts == 2


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


def test_cleanup_keeps_pending_reference_and_sweeps_stale_orphan(
    repository: InMemoryCleanupRepository,
    verification_repository: InMemoryCleanupVerificationRepository,
    storage: JobStorage,
) -> None:
    from text_verification.workers.tasks import cleanup_expired_jobs

    live_job = repository.create_job(
        status=JobStatus.COMPLETED,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    pending_id = uuid4()
    orphan_job_id = uuid4()
    orphan_id = uuid4()
    recent_id = uuid4()
    pending = _publish_artifact_fixture(
        storage,
        live_job.job_id,
        pending_id,
        b"pending",
    )
    orphan = _publish_artifact_fixture(
        storage,
        orphan_job_id,
        orphan_id,
        b"orphan",
    )
    recent = _publish_artifact_fixture(
        storage,
        live_job.job_id,
        recent_id,
        b"recent",
    )
    recent_temp = recent.path.with_name(f".{recent.path.name}.active.uploading")
    recent_temp.write_bytes(b"in progress")
    stale_timestamp = (datetime.now(UTC) - timedelta(hours=25)).timestamp()
    os.utime(pending.path, (stale_timestamp, stale_timestamp))
    os.utime(orphan.path, (stale_timestamp, stale_timestamp))
    os.utime(orphan.path.parent, (stale_timestamp, stale_timestamp))
    verification_repository.artifact_keys[live_job.job_id] = (
        pending.storage_key,
    )

    cleanup_expired_jobs()

    assert pending.path.exists()
    assert not orphan.path.exists()
    assert not orphan.path.parent.exists()
    assert recent.path.exists()
    assert recent_temp.exists()


def test_cleanup_removes_stale_unreferenced_artifact_uploading_file(
    storage: JobStorage,
) -> None:
    from text_verification.workers.tasks import cleanup_expired_jobs

    job_id = uuid4()
    artifact_id = uuid4()
    storage_key = build_artifact_storage_key(job_id, artifact_id, FileType.TXT)
    upload_path = storage._root / storage_key
    upload_path = upload_path.with_name(
        f".{upload_path.name}.{uuid4().hex}.uploading"
    )
    upload_path.parent.mkdir(parents=True)
    upload_path.write_bytes(b"abandoned upload")
    stale_timestamp = (datetime.now(UTC) - timedelta(hours=25)).timestamp()
    os.utime(upload_path, (stale_timestamp, stale_timestamp))

    cleanup_expired_jobs()

    assert not upload_path.exists()
    assert not upload_path.parent.exists()


def test_cleanup_removes_stale_uploading_file_for_referenced_final_artifact(
    repository: InMemoryCleanupRepository,
    verification_repository: InMemoryCleanupVerificationRepository,
    storage: JobStorage,
) -> None:
    from text_verification.workers.tasks import cleanup_expired_jobs

    job = repository.create_job(
        status=JobStatus.COMPLETED,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    artifact_id = uuid4()
    storage_key = build_artifact_storage_key(job.job_id, artifact_id, FileType.TXT)
    upload_path = (storage._root / storage_key).with_name(
        f".{artifact_id}.txt.{uuid4().hex}.uploading"
    )
    upload_path.parent.mkdir(parents=True)
    upload_path.write_bytes(b"abandoned upload")
    verification_repository.artifact_keys[job.job_id] = (storage_key,)
    stale_timestamp = (datetime.now(UTC) - timedelta(hours=25)).timestamp()
    os.utime(upload_path, (stale_timestamp, stale_timestamp))

    cleanup_expired_jobs()

    assert not upload_path.exists()
    assert upload_path.parent.exists()


def test_cleanup_rejects_symlink_in_artifact_orphan_sweep(
    repository: InMemoryCleanupRepository,
    storage: JobStorage,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from text_verification.workers.tasks import cleanup_expired_jobs

    live_job = repository.create_job(
        status=JobStatus.COMPLETED,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    outside = tmp_path / "outside-artifacts"
    outside.mkdir()
    outside_file = outside / "keep.txt"
    outside_file.write_text("keep", encoding="utf-8")
    link = storage._root / "artifacts" / str(live_job.job_id) / "link"
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlink creation unavailable: {error}")

    with caplog.at_level(logging.WARNING, logger="text_verification.infrastructure.storage"):
        cleanup_expired_jobs()

    assert link.is_symlink()
    assert outside_file.read_text(encoding="utf-8") == "keep"
    assert [record.getMessage() for record in caplog.records] == [
        "cleanup_orphaned_artifact_delete_failed"
    ]


def test_compatibility_cleanup_deletes_only_stale_canonical_uuid_directories(
    compatibility_storage: CompatibilityStorage,
    tmp_path: Path,
) -> None:
    stale_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    fresh_id = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    symlink_id = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
    compatibility_storage.save_stream(stale_id, "stale.txt", BytesIO(b"stale"))
    compatibility_storage.save_stream(fresh_id, "fresh.txt", BytesIO(b"fresh"))

    compatibility_root = tmp_path / "jobs" / "compatibility"
    noncanonical = compatibility_root / stale_id.hex
    noncanonical.mkdir()
    (noncanonical / "source.txt").write_bytes(b"noncanonical")
    non_uuid = compatibility_root / "not-a-uuid"
    non_uuid.mkdir()
    canonical_file = compatibility_root / "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
    canonical_file.write_bytes(b"not a directory")
    outside = tmp_path / "outside"
    outside.mkdir()
    symlink = compatibility_root / str(symlink_id)
    symlink.symlink_to(outside, target_is_directory=True)

    stale_timestamp = (datetime.now(UTC) - timedelta(hours=25)).timestamp()
    os.utime(compatibility_root / str(stale_id), (stale_timestamp, stale_timestamp))
    os.utime(noncanonical, (stale_timestamp, stale_timestamp))
    os.utime(non_uuid, (stale_timestamp, stale_timestamp))

    deleted_ids = compatibility_storage.delete_stale_directories(
        datetime.now(UTC) - timedelta(hours=24)
    )

    assert deleted_ids == [stale_id]
    assert not (compatibility_root / str(stale_id)).exists()
    assert (compatibility_root / str(fresh_id)).exists()
    assert noncanonical.exists()
    assert non_uuid.exists()
    assert canonical_file.exists()
    assert symlink.is_symlink()
    assert outside.exists()


def test_hourly_cleanup_removes_stale_compatibility_upload_without_changing_result(
    compatibility_storage: CompatibilityStorage,
) -> None:
    from text_verification.workers.tasks import cleanup_expired_jobs

    file_id = uuid4()
    stored = compatibility_storage.save_stream(file_id, "source.txt", BytesIO(b"content"))
    stale_timestamp = (datetime.now(UTC) - timedelta(hours=25)).timestamp()
    os.utime(stored.path.parent, (stale_timestamp, stale_timestamp))

    deleted_job_ids = cleanup_expired_jobs()

    assert deleted_job_ids == []
    assert not stored.path.parent.exists()


def test_cleanup_is_scheduled_hourly() -> None:
    from text_verification.workers.celery_app import celery_app

    assert celery_app.conf.beat_schedule["cleanup-expired-jobs-hourly"] == {
        "task": "text_verification.cleanup_expired_jobs",
        "schedule": 3600.0,
    }


def test_expired_lease_rescue_is_scheduled_every_minute() -> None:
    from text_verification.workers.celery_app import celery_app

    assert celery_app.conf.beat_schedule["rescue-expired-job-leases"] == {
        "task": "text_verification.rescue_expired_job_leases",
        "schedule": 60.0,
    }
