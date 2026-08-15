from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from text_verification.domain.documents import FileType
from text_verification.domain.jobs import JobEvent, JobRead, JobStatus
from text_verification.infrastructure.storage import JobStorage


class InMemoryJobRepository:
    def __init__(self, *, fail_on_commit_calls: set[int] | None = None) -> None:
        self._fail_on_commit_calls = fail_on_commit_calls or set()
        self._commit_count = 0
        self.rollback_calls = 0
        self._jobs: dict[UUID, JobRead] = {}
        self._events: dict[UUID, list[JobEvent]] = {}
        self._reset_working_copy()

    def create_job(
        self,
        *,
        job_id: UUID,
        source_name: str,
        file_type: str,
        size_bytes: int,
        storage_key: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> JobRead:
        del storage_key
        job = JobRead(
            job_id=job_id,
            source_name=source_name,
            file_type=FileType(file_type),
            size_bytes=size_bytes,
            status=JobStatus.QUEUED,
            progress=0,
            created_at=created_at,
            expires_at=expires_at,
        )
        self._working_jobs[job_id] = job
        self._working_events[job_id] = [
            JobEvent(
                sequence=1,
                status=JobStatus.QUEUED,
                progress=0,
                message="作业已创建",
                created_at=created_at,
            )
        ]
        return job

    def get_job(self, job_id: UUID) -> JobRead | None:
        return self._jobs.get(job_id)

    def transition(
        self,
        job_id: UUID,
        status: JobStatus,
        progress: int,
        message: str,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        current_job = self._working_jobs[job_id]
        self._working_jobs[job_id] = current_job.model_copy(
            update={
                "status": status,
                "progress": progress,
                "error_code": error_code,
                "error_message": error_message,
            }
        )
        self._working_events[job_id].append(
            JobEvent(
                sequence=len(self._working_events[job_id]) + 1,
                status=status,
                progress=progress,
                message=message,
                created_at=datetime.now(UTC),
            )
        )

    def list_events_after(self, job_id: UUID, after_sequence: int) -> list[JobEvent]:
        return [
            event for event in self._events.get(job_id, []) if event.sequence > after_sequence
        ]

    def commit(self) -> None:
        self._commit_count += 1
        if self._commit_count in self._fail_on_commit_calls:
            raise RuntimeError("database unavailable")
        self._jobs = {
            job_id: job.model_copy(deep=True) for job_id, job in self._working_jobs.items()
        }
        self._events = {
            job_id: [event for event in events] for job_id, events in self._working_events.items()
        }
        self._reset_working_copy()

    def rollback(self) -> None:
        self.rollback_calls += 1
        self._reset_working_copy()

    def _reset_working_copy(self) -> None:
        self._working_jobs = {
            job_id: job.model_copy(deep=True) for job_id, job in self._jobs.items()
        }
        self._working_events = {
            job_id: [event for event in events] for job_id, events in self._events.items()
        }


@dataclass
class FakeSession:
    closed: bool = False

    def close(self) -> None:
        self.closed = True


@dataclass
class SessionFactorySpy:
    sessions: list[FakeSession] = field(default_factory=list)

    def __call__(self) -> FakeSession:
        session = FakeSession()
        self.sessions.append(session)
        return session


@dataclass
class ExplodingRunner:
    error: Exception

    def run(self, job_id: UUID) -> None:
        del job_id
        raise self.error


@dataclass
class ExplodingFactory:
    error: Exception

    def __call__(self, *args, **kwargs):
        del args, kwargs
        raise self.error


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
def worker_storage(tmp_path) -> JobStorage:
    root = tmp_path / "worker-jobs"
    root.mkdir()
    return JobStorage(root, max_upload_bytes=25 * 1024 * 1024)


def _seed_txt_job(
    repository: InMemoryJobRepository,
    storage: JobStorage,
    *,
    persist_source: bool = True,
) -> UUID:
    job_id = uuid4()
    created_at = datetime.now(UTC)
    size_bytes = 8

    if persist_source:
        stored = storage.save_bytes(job_id, "sample.txt", "需要检查".encode())
        size_bytes = stored.size_bytes

    repository.create_job(
        job_id=job_id,
        source_name="sample.txt",
        file_type=FileType.TXT.value,
        size_bytes=size_bytes,
        storage_key=str(job_id),
        created_at=created_at,
        expires_at=created_at + timedelta(hours=24),
    )
    repository.commit()
    return job_id


def _configure_worker_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    repository: InMemoryJobRepository,
    storage: JobStorage,
    *,
    runner_factory=None,
) -> SessionFactorySpy:
    from text_verification.workers import tasks as worker_tasks

    session_factory = SessionFactorySpy()
    monkeypatch.setattr(worker_tasks, "SESSION_FACTORY_PROVIDER", lambda: session_factory)
    monkeypatch.setattr(worker_tasks, "STORAGE_FACTORY", lambda: storage)
    monkeypatch.setattr(worker_tasks, "REPOSITORY_FACTORY", lambda session: repository)
    if runner_factory is not None:
        monkeypatch.setattr(worker_tasks, "RUNNER_FACTORY", runner_factory)
    return session_factory


def test_process_job_eager_task_completes_job(monkeypatch, worker_storage, celery_eager) -> None:
    from text_verification.workers.tasks import process_job

    repository = InMemoryJobRepository()
    job_id = _seed_txt_job(repository, worker_storage)
    session_factory = _configure_worker_dependencies(monkeypatch, repository, worker_storage)

    result = process_job.delay(str(job_id))

    assert result.successful()
    job = repository.get_job(job_id)
    assert job is not None
    assert job.status == JobStatus.COMPLETED
    assert job.progress == 100
    assert [event.status for event in repository.list_events_after(job_id, 0)] == [
        JobStatus.QUEUED,
        JobStatus.UPLOAD_VALIDATED,
        JobStatus.PARSING,
        JobStatus.COMPLETED,
    ]
    assert len(session_factory.sessions) == 1
    assert session_factory.sessions[0].closed is True


def test_process_job_redelivery_from_upload_validated_only_advances_remaining_states(
    monkeypatch,
    worker_storage,
    celery_eager,
) -> None:
    from text_verification.workers.tasks import process_job

    repository = InMemoryJobRepository()
    job_id = _seed_txt_job(repository, worker_storage)
    repository.transition(job_id, JobStatus.UPLOAD_VALIDATED, 10, "上传校验完成")
    repository.commit()
    _configure_worker_dependencies(monkeypatch, repository, worker_storage)

    result = process_job.delay(str(job_id))

    assert result.successful()
    assert [event.sequence for event in repository.list_events_after(job_id, 0)] == [1, 2, 3, 4]
    assert [event.status for event in repository.list_events_after(job_id, 0)] == [
        JobStatus.QUEUED,
        JobStatus.UPLOAD_VALIDATED,
        JobStatus.PARSING,
        JobStatus.COMPLETED,
    ]


def test_process_job_redelivery_from_parsing_only_completes_job(
    monkeypatch,
    worker_storage,
    celery_eager,
) -> None:
    from text_verification.workers.tasks import process_job

    repository = InMemoryJobRepository()
    job_id = _seed_txt_job(repository, worker_storage)
    repository.transition(job_id, JobStatus.UPLOAD_VALIDATED, 10, "上传校验完成")
    repository.transition(job_id, JobStatus.PARSING, 25, "开始解析")
    repository.commit()
    _configure_worker_dependencies(monkeypatch, repository, worker_storage)

    result = process_job.delay(str(job_id))

    assert result.successful()
    assert [event.sequence for event in repository.list_events_after(job_id, 0)] == [1, 2, 3, 4]
    assert [event.status for event in repository.list_events_after(job_id, 0)] == [
        JobStatus.QUEUED,
        JobStatus.UPLOAD_VALIDATED,
        JobStatus.PARSING,
        JobStatus.COMPLETED,
    ]


def test_process_job_fails_expected_validation_with_safe_message(
    monkeypatch,
    worker_storage,
    celery_eager,
) -> None:
    from text_verification.workers.tasks import process_job

    repository = InMemoryJobRepository()
    job_id = _seed_txt_job(repository, worker_storage, persist_source=False)
    _configure_worker_dependencies(monkeypatch, repository, worker_storage)

    result = process_job.delay(str(job_id))

    assert result.successful()
    job = repository.get_job(job_id)
    assert job is not None
    assert job.status == JobStatus.FAILED
    assert job.progress < 100
    assert job.error_code == "pipeline_failed"
    assert job.error_message == "Stored upload is unavailable."
    assert str(worker_storage._root).lower() not in job.error_message.lower()
    assert "\\" not in job.error_message
    assert [event.status for event in repository.list_events_after(job_id, 0)] == [
        JobStatus.QUEUED,
        JobStatus.UPLOAD_VALIDATED,
        JobStatus.PARSING,
        JobStatus.FAILED,
    ]


def test_process_job_noops_when_job_is_missing(
    monkeypatch,
    worker_storage,
    celery_eager,
) -> None:
    from text_verification.workers.tasks import process_job

    repository = InMemoryJobRepository()
    session_factory = _configure_worker_dependencies(monkeypatch, repository, worker_storage)

    result = process_job.delay(str(uuid4()))

    assert result.successful()
    assert repository._jobs == {}
    assert len(session_factory.sessions) == 1
    assert session_factory.sessions[0].closed is True


def test_process_job_noops_when_job_is_terminal(
    monkeypatch,
    worker_storage,
    celery_eager,
) -> None:
    from text_verification.workers.tasks import process_job

    repository = InMemoryJobRepository()
    job_id = _seed_txt_job(repository, worker_storage)
    repository.transition(job_id, JobStatus.COMPLETED, 100, "处理完成")
    repository.commit()
    _configure_worker_dependencies(monkeypatch, repository, worker_storage)

    result = process_job.delay(str(job_id))

    assert result.successful()
    assert [event.status for event in repository.list_events_after(job_id, 0)] == [
        JobStatus.QUEUED,
        JobStatus.COMPLETED,
    ]


def test_process_job_persists_failed_state_before_reraising_unexpected_errors(
    monkeypatch,
    worker_storage,
    celery_eager,
) -> None:
    from text_verification.workers.tasks import process_job

    repository = InMemoryJobRepository()
    job_id = _seed_txt_job(repository, worker_storage)
    _configure_worker_dependencies(
        monkeypatch,
        repository,
        worker_storage,
        runner_factory=lambda repository, storage: ExplodingRunner(RuntimeError("parser offline")),
    )

    result = process_job.delay(str(job_id))

    assert result.failed()
    assert isinstance(result.result, RuntimeError)
    assert str(result.result) == "parser offline"
    job = repository.get_job(job_id)
    assert job is not None
    assert job.status == JobStatus.FAILED
    assert job.error_code == "pipeline_failed"
    assert job.error_message == "Processing failed."


def test_process_job_persists_failed_state_when_storage_factory_raises(
    monkeypatch,
    worker_storage,
    celery_eager,
    caplog,
) -> None:
    from text_verification.workers.tasks import process_job

    repository = InMemoryJobRepository()
    job_id = _seed_txt_job(repository, worker_storage)
    _configure_worker_dependencies(monkeypatch, repository, worker_storage)
    from text_verification.workers import tasks as worker_tasks

    monkeypatch.setattr(
        worker_tasks,
        "STORAGE_FACTORY",
        ExplodingFactory(RuntimeError("storage root leaked")),
    )

    with caplog.at_level(logging.ERROR, logger="text_verification.workers.tasks"):
        result = process_job.delay(str(job_id))

    assert result.failed()
    assert isinstance(result.result, RuntimeError)
    assert str(result.result) == "storage root leaked"
    job = repository.get_job(job_id)
    assert job is not None
    assert job.status == JobStatus.FAILED
    assert job.error_code == "pipeline_failed"
    assert job.error_message == "Processing failed."
    task_records = [
        record for record in caplog.records if record.name == "text_verification.workers.tasks"
    ]
    assert [record.getMessage() for record in task_records] == ["process_job_failed"]
    assert task_records[0].job_id == str(job_id)
    assert task_records[0].error_type == "RuntimeError"
    assert all("storage root leaked" not in record.getMessage() for record in task_records)
    assert all(str(worker_storage._root) not in record.getMessage() for record in task_records)


def test_process_job_persists_failed_state_when_runner_factory_raises(
    monkeypatch,
    worker_storage,
    celery_eager,
    caplog,
) -> None:
    from text_verification.workers.tasks import process_job

    repository = InMemoryJobRepository()
    job_id = _seed_txt_job(repository, worker_storage)
    _configure_worker_dependencies(monkeypatch, repository, worker_storage)
    from text_verification.workers import tasks as worker_tasks

    monkeypatch.setattr(
        worker_tasks,
        "RUNNER_FACTORY",
        ExplodingFactory(RuntimeError("runner setup leaked")),
    )

    with caplog.at_level(logging.ERROR, logger="text_verification.workers.tasks"):
        result = process_job.delay(str(job_id))

    assert result.failed()
    assert isinstance(result.result, RuntimeError)
    assert str(result.result) == "runner setup leaked"
    job = repository.get_job(job_id)
    assert job is not None
    assert job.status == JobStatus.FAILED
    assert job.error_code == "pipeline_failed"
    assert job.error_message == "Processing failed."
    task_records = [
        record for record in caplog.records if record.name == "text_verification.workers.tasks"
    ]
    assert [record.getMessage() for record in task_records] == ["process_job_failed"]
    assert task_records[0].job_id == str(job_id)
    assert task_records[0].error_type == "RuntimeError"
    assert all("runner setup leaked" not in record.getMessage() for record in task_records)


def test_process_job_logs_both_errors_when_failure_persistence_fails(
    monkeypatch,
    worker_storage,
    celery_eager,
    caplog,
) -> None:
    from text_verification.workers.tasks import process_job

    repository = InMemoryJobRepository(fail_on_commit_calls={2})
    job_id = _seed_txt_job(repository, worker_storage)
    _configure_worker_dependencies(
        monkeypatch,
        repository,
        worker_storage,
        runner_factory=lambda repository, storage: ExplodingRunner(RuntimeError("parser offline")),
    )

    with caplog.at_level(logging.ERROR, logger="text_verification.workers.tasks"):
        result = process_job.delay(str(job_id))

    assert result.failed()
    assert isinstance(result.result, RuntimeError)
    assert str(result.result) == "parser offline"
    job = repository.get_job(job_id)
    assert job is not None
    assert job.status == JobStatus.QUEUED
    assert repository.rollback_calls == 1
    task_records = [
        record for record in caplog.records if record.name == "text_verification.workers.tasks"
    ]
    assert [record.getMessage() for record in task_records] == [
        "process_job_failure_persist_failed",
        "process_job_failed",
    ]
    assert task_records[0].job_id == str(job_id)
    assert task_records[0].original_error_type == "RuntimeError"
    assert task_records[0].persistence_error_type == "RuntimeError"
    assert task_records[1].job_id == str(job_id)
    assert task_records[1].error_type == "RuntimeError"
    assert all("database unavailable" not in record.getMessage() for record in task_records)
    assert all("parser offline" not in record.getMessage() for record in task_records)
