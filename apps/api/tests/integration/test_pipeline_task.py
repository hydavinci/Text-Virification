from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from text_verification.application import (
    VerificationCommand,
    VerificationError,
    VerificationPipeline,
    build_default_verification_pipeline,
)
from text_verification.config import Settings
from text_verification.domain.documents import FileType
from text_verification.domain.jobs import (
    TERMINAL_STATUSES,
    JobEvent,
    JobRead,
    JobStatus,
    TerminalJobStateError,
)
from text_verification.domain.verification import (
    VerificationExecutionMode,
    VerificationOptions,
    VerificationResult,
)
from text_verification.infrastructure.repositories import JobRepository as SqlJobRepository
from text_verification.infrastructure.storage import InvalidUpload, JobStorage
from text_verification.infrastructure.verification_repository import VerificationRepository

COMPLETED_STATUS_SEQUENCE = [
    JobStatus.QUEUED,
    JobStatus.UPLOAD_VALIDATED,
    JobStatus.PARSING,
    JobStatus.CHECKING_FORMAT,
    JobStatus.CHECKING_SENSITIVE,
    JobStatus.CHECKING_CHINESE,
    JobStatus.CHECKING_ENGLISH,
    JobStatus.COMPLETED,
]


class InMemoryJobRepository:
    def __init__(
        self,
        *,
        fail_on_commit_calls: set[int] | None = None,
        operations: list[str] | None = None,
    ) -> None:
        self._fail_on_commit_calls = fail_on_commit_calls or set()
        self._operations = operations
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
        if current_job.status in TERMINAL_STATUSES:
            raise TerminalJobStateError(
                job_id=job_id,
                current_status=current_job.status,
                target_status=status,
            )
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
        if self._operations is not None:
            self._operations.extend(
                f"job:{job.status.value}" for job in self._jobs.values()
            )
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


class InMemoryVerificationRepository:
    def __init__(self, *, operations: list[str] | None = None) -> None:
        self._operations = operations
        self.rollback_calls = 0
        self._results: dict[UUID, VerificationResult] = {}
        self._working_results: dict[UUID, VerificationResult] = {}

    def save_result(self, job_id: UUID, result: VerificationResult) -> None:
        existing = self._working_results.get(job_id)
        if existing is not None and existing != result:
            raise ValueError(f"Job {job_id} already has a different result.")
        self._working_results[job_id] = result.model_copy(deep=True)

    def get_result_for_job(self, job_id: UUID) -> VerificationResult | None:
        result = self._results.get(job_id)
        return None if result is None else result.model_copy(deep=True)

    def commit(self) -> None:
        self._results = {
            job_id: result.model_copy(deep=True)
            for job_id, result in self._working_results.items()
        }
        if self._operations is not None:
            self._operations.append("result")

    def rollback(self) -> None:
        self.rollback_calls += 1
        self._working_results = {
            job_id: result.model_copy(deep=True)
            for job_id, result in self._results.items()
        }


class ExpiringOnFirstTransitionRepository(InMemoryJobRepository):
    def __init__(self) -> None:
        super().__init__()
        self._expired_job_ids: set[UUID] = set()

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
        if status == JobStatus.UPLOAD_VALIDATED and job_id not in self._expired_job_ids:
            current_job = self._jobs[job_id]
            self._jobs[job_id] = current_job.model_copy(update={"status": JobStatus.EXPIRED})
            self._events[job_id].append(
                JobEvent(
                    sequence=len(self._events[job_id]) + 1,
                    status=JobStatus.EXPIRED,
                    progress=current_job.progress,
                    message="作业已过期",
                    created_at=datetime.now(UTC),
                )
            )
            self._expired_job_ids.add(job_id)
            self._reset_working_copy()
        super().transition(
            job_id,
            status,
            progress,
            message,
            error_code=error_code,
            error_message=error_message,
        )


class ExpiringOnCompletionRepository(InMemoryJobRepository):
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
        if status == JobStatus.COMPLETED:
            current_job = self._jobs[job_id]
            self._jobs[job_id] = current_job.model_copy(update={"status": JobStatus.EXPIRED})
            self._events[job_id].append(
                JobEvent(
                    sequence=len(self._events[job_id]) + 1,
                    status=JobStatus.EXPIRED,
                    progress=current_job.progress,
                    message="作业已过期",
                    created_at=datetime.now(UTC),
                )
            )
            self._reset_working_copy()
        super().transition(
            job_id,
            status,
            progress,
            message,
            error_code=error_code,
            error_message=error_message,
        )


class FlakyGetJobRepository(InMemoryJobRepository):
    def __init__(self) -> None:
        super().__init__()
        self.failures_remaining = 1

    def get_job(self, job_id: UUID) -> JobRead | None:
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise RuntimeError("database unavailable")
        return super().get_job(job_id)


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
class FlakyRunnerFactory:
    failures_remaining: int
    attempts: int = 0

    def __call__(self, repository, verification_repository, storage, pipeline):
        from text_verification.workers.pipeline import PipelineRunner

        self.attempts += 1
        if self.failures_remaining:
            self.failures_remaining -= 1
            return ExplodingRunner(RuntimeError("transient parser failure"))
        return PipelineRunner(repository, verification_repository, storage, pipeline)


@dataclass
class RecordingPipeline:
    delegate: VerificationPipeline
    commands: list[VerificationCommand] = field(default_factory=list)

    def run(self, command: VerificationCommand) -> VerificationResult:
        self.commands.append(command)
        return self.delegate.run(command)


@dataclass
class FlakyVerificationPipeline:
    delegate: VerificationPipeline
    error: VerificationError
    failures_remaining: int
    attempts: int = 0

    def run(self, command: VerificationCommand) -> VerificationResult:
        self.attempts += 1
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise self.error
        return self.delegate.run(command)


@dataclass
class FlakySessionFactory:
    failures_remaining: int
    calls: int = 0
    sessions: list[FakeSession] = field(default_factory=list)

    def __call__(self) -> FakeSession:
        self.calls += 1
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise RuntimeError("transient session failure")
        session = FakeSession()
        self.sessions.append(session)
        return session


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
    verification_repository: InMemoryVerificationRepository | None = None,
    pipeline: VerificationPipeline | None = None,
) -> SessionFactorySpy:
    from text_verification.workers import tasks as worker_tasks

    session_factory = SessionFactorySpy()
    verification_repository = verification_repository or InMemoryVerificationRepository()
    pipeline = pipeline or build_default_verification_pipeline(Settings(llm_api_key=""))
    monkeypatch.setattr(worker_tasks, "SESSION_FACTORY_PROVIDER", lambda: session_factory)
    monkeypatch.setattr(worker_tasks, "STORAGE_FACTORY", lambda: storage)
    monkeypatch.setattr(worker_tasks, "REPOSITORY_FACTORY", lambda session: repository)
    monkeypatch.setattr(
        worker_tasks,
        "VERIFICATION_REPOSITORY_FACTORY",
        lambda session: verification_repository,
        raising=False,
    )
    monkeypatch.setattr(worker_tasks, "PIPELINE_FACTORY", lambda: pipeline, raising=False)
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
    assert [
        event.status for event in repository.list_events_after(job_id, 0)
    ] == COMPLETED_STATUS_SEQUENCE
    assert len(session_factory.sessions) == 1
    assert session_factory.sessions[0].closed is True


def test_process_job_persists_pipeline_result_before_completing_job(
    monkeypatch,
    worker_storage,
    celery_eager,
) -> None:
    from text_verification.workers.tasks import process_job

    operations: list[str] = []
    repository = InMemoryJobRepository(operations=operations)
    verification_repository = InMemoryVerificationRepository(operations=operations)
    pipeline = RecordingPipeline(
        build_default_verification_pipeline(Settings(llm_api_key=""))
    )
    job_id = _seed_txt_job(repository, worker_storage)
    _configure_worker_dependencies(
        monkeypatch,
        repository,
        worker_storage,
        verification_repository=verification_repository,
        pipeline=pipeline,
    )

    result = process_job.delay(str(job_id))

    assert result.successful()
    persisted = verification_repository.get_result_for_job(job_id)
    assert persisted is not None
    assert persisted.document_id == job_id
    assert persisted.source_name == "sample.txt"
    assert persisted.file_type is FileType.TXT
    assert persisted.execution_mode is VerificationExecutionMode.ASYNCHRONOUS
    assert len(pipeline.commands) == 1
    assert pipeline.commands[0] == VerificationCommand(
        document_id=job_id,
        source_path=worker_storage.source_path(job_id, FileType.TXT),
        direct_text=None,
        source_name="sample.txt",
        file_type=FileType.TXT,
        options=VerificationOptions(),
        execution_mode=VerificationExecutionMode.ASYNCHRONOUS,
    )
    assert operations.index("result") < operations.index("job:completed")


def test_pipeline_runner_persists_result_in_postgresql(
    db_session: Session,
    worker_storage: JobStorage,
) -> None:
    from text_verification.workers.pipeline import PipelineRunner

    job_id = uuid4()
    created_at = datetime.now(UTC)
    stored = worker_storage.save_bytes(job_id, "sample.txt", "需要检查".encode())
    repository = SqlJobRepository(db_session)
    repository.create_job(
        job_id=job_id,
        source_name=stored.original_name,
        file_type=stored.file_type,
        size_bytes=stored.size_bytes,
        storage_key=str(job_id),
        created_at=created_at,
        expires_at=created_at + timedelta(hours=24),
    )
    repository.commit()
    verification_repository = VerificationRepository(db_session)
    runner = PipelineRunner(
        repository,
        verification_repository,
        worker_storage,
        build_default_verification_pipeline(Settings(llm_api_key="")),
    )

    runner.run(job_id)

    result = verification_repository.get_result_for_job(job_id)
    assert result is not None
    assert result.document_id == job_id
    assert result.source_name == "sample.txt"
    assert result.execution_mode is VerificationExecutionMode.ASYNCHRONOUS
    assert repository.get_job(job_id).status is JobStatus.COMPLETED


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
    assert [event.sequence for event in repository.list_events_after(job_id, 0)] == list(
        range(1, 9)
    )
    assert [
        event.status for event in repository.list_events_after(job_id, 0)
    ] == COMPLETED_STATUS_SEQUENCE


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
    assert [event.sequence for event in repository.list_events_after(job_id, 0)] == list(
        range(1, 9)
    )
    assert [
        event.status for event in repository.list_events_after(job_id, 0)
    ] == COMPLETED_STATUS_SEQUENCE


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


def test_process_job_does_not_retry_non_retryable_pipeline_error(
    monkeypatch,
    worker_storage,
    celery_eager,
) -> None:
    from text_verification.workers.tasks import process_job

    repository = InMemoryJobRepository()
    job_id = _seed_txt_job(repository, worker_storage)
    pipeline = FlakyVerificationPipeline(
        delegate=build_default_verification_pipeline(Settings(llm_api_key="")),
        error=VerificationError(
            "parser_failed",
            "parsing",
            "The source document could not be parsed.",
            False,
        ),
        failures_remaining=1,
    )
    session_factory = _configure_worker_dependencies(
        monkeypatch,
        repository,
        worker_storage,
        pipeline=pipeline,
    )

    result = process_job.delay(str(job_id))

    assert result.successful()
    assert pipeline.attempts == 1
    assert len(session_factory.sessions) == 1
    job = repository.get_job(job_id)
    assert job is not None
    assert job.status is JobStatus.FAILED
    assert job.error_code == "pipeline_failed"
    assert job.error_message == "The source document could not be parsed."


def test_process_job_retries_retryable_pipeline_error_without_failed_event(
    monkeypatch,
    worker_storage,
    celery_eager,
) -> None:
    from text_verification.workers.tasks import process_job

    repository = InMemoryJobRepository()
    job_id = _seed_txt_job(repository, worker_storage)
    pipeline = FlakyVerificationPipeline(
        delegate=build_default_verification_pipeline(Settings(llm_api_key="")),
        error=VerificationError(
            "source_read_failed",
            "parsing",
            "The stored source document could not be read.",
            True,
        ),
        failures_remaining=1,
    )
    session_factory = _configure_worker_dependencies(
        monkeypatch,
        repository,
        worker_storage,
        pipeline=pipeline,
    )

    result = process_job.delay(str(job_id))

    assert result.successful()
    assert pipeline.attempts == 2
    assert len(session_factory.sessions) == 2
    assert repository.get_job(job_id).status is JobStatus.COMPLETED
    assert JobStatus.FAILED not in [
        event.status for event in repository.list_events_after(job_id, 0)
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


def test_process_job_stops_when_cleanup_expires_job_before_pipeline_transition(
    monkeypatch,
    worker_storage,
    celery_eager,
) -> None:
    from text_verification.workers.tasks import process_job

    repository = ExpiringOnFirstTransitionRepository()
    job_id = _seed_txt_job(repository, worker_storage)
    _configure_worker_dependencies(monkeypatch, repository, worker_storage)

    result = process_job.delay(str(job_id))

    assert result.successful()
    job = repository.get_job(job_id)
    assert job is not None
    assert job.status == JobStatus.EXPIRED
    assert [event.status for event in repository.list_events_after(job_id, 0)] == [
        JobStatus.QUEUED,
        JobStatus.EXPIRED,
    ]


def test_process_job_keeps_expired_terminal_state_when_completion_transition_loses_race(
    monkeypatch,
    worker_storage,
    celery_eager,
) -> None:
    from text_verification.workers.tasks import process_job

    repository = ExpiringOnCompletionRepository()
    verification_repository = InMemoryVerificationRepository()
    job_id = _seed_txt_job(repository, worker_storage)
    _configure_worker_dependencies(
        monkeypatch,
        repository,
        worker_storage,
        verification_repository=verification_repository,
    )

    result = process_job.delay(str(job_id))

    assert result.successful()
    assert verification_repository.get_result_for_job(job_id) is not None
    assert repository.get_job(job_id).status is JobStatus.EXPIRED
    assert JobStatus.COMPLETED not in [
        event.status for event in repository.list_events_after(job_id, 0)
    ]


def test_process_job_reuses_committed_result_when_completion_commit_is_retried(
    monkeypatch,
    worker_storage,
    celery_eager,
) -> None:
    from text_verification.workers.tasks import process_job

    repository = InMemoryJobRepository(fail_on_commit_calls={8})
    verification_repository = InMemoryVerificationRepository()
    pipeline = RecordingPipeline(
        build_default_verification_pipeline(Settings(llm_api_key=""))
    )
    job_id = _seed_txt_job(repository, worker_storage)
    session_factory = _configure_worker_dependencies(
        monkeypatch,
        repository,
        worker_storage,
        verification_repository=verification_repository,
        pipeline=pipeline,
    )

    result = process_job.delay(str(job_id))

    assert result.successful()
    assert len(pipeline.commands) == 1
    assert verification_repository.get_result_for_job(job_id) is not None
    assert repository.get_job(job_id).status is JobStatus.COMPLETED
    assert len(session_factory.sessions) == 2
    assert all(session.closed for session in session_factory.sessions)


def test_process_job_retries_transient_unexpected_failure_without_failed_event(
    monkeypatch,
    worker_storage,
    celery_eager,
) -> None:
    from text_verification.workers.tasks import process_job

    repository = InMemoryJobRepository()
    job_id = _seed_txt_job(repository, worker_storage)
    runner_factory = FlakyRunnerFactory(failures_remaining=1)
    session_factory = _configure_worker_dependencies(
        monkeypatch,
        repository,
        worker_storage,
        runner_factory=runner_factory,
    )

    result = process_job.delay(str(job_id))

    assert result.successful()
    assert runner_factory.attempts == 2
    job = repository.get_job(job_id)
    assert job is not None
    assert job.status == JobStatus.COMPLETED
    assert JobStatus.FAILED not in [
        event.status for event in repository.list_events_after(job_id, 0)
    ]
    assert len(session_factory.sessions) == 2
    assert all(session.closed for session in session_factory.sessions)


def test_process_job_persists_one_failed_event_after_unexpected_retries_exhausted(
    monkeypatch,
    worker_storage,
    celery_eager,
) -> None:
    from text_verification.workers.tasks import process_job

    repository = InMemoryJobRepository()
    job_id = _seed_txt_job(repository, worker_storage)
    runner_factory = FlakyRunnerFactory(failures_remaining=10)
    session_factory = _configure_worker_dependencies(
        monkeypatch,
        repository,
        worker_storage,
        runner_factory=runner_factory,
    )

    result = process_job.delay(str(job_id))

    assert result.failed()
    assert isinstance(result.result, RuntimeError)
    assert str(result.result) == "transient parser failure"
    assert runner_factory.attempts == 3
    job = repository.get_job(job_id)
    assert job is not None
    assert job.status == JobStatus.FAILED
    assert job.error_code == "pipeline_failed"
    assert job.error_message == "Processing failed."
    assert [
        event.status for event in repository.list_events_after(job_id, 0)
    ].count(JobStatus.FAILED) == 1
    assert len(session_factory.sessions) == 4
    assert all(session.closed for session in session_factory.sessions)


def test_process_job_invalid_upload_is_not_retried(
    monkeypatch,
    worker_storage,
    celery_eager,
) -> None:
    from text_verification.workers.tasks import process_job

    repository = InMemoryJobRepository()
    job_id = _seed_txt_job(repository, worker_storage)
    attempts = 0

    def invalid_runner_factory(repository, verification_repository, storage, pipeline):
        del repository, verification_repository, storage, pipeline
        nonlocal attempts
        attempts += 1
        return ExplodingRunner(InvalidUpload("invalid upload"))

    session_factory = _configure_worker_dependencies(
        monkeypatch,
        repository,
        worker_storage,
        runner_factory=invalid_runner_factory,
    )

    result = process_job.delay(str(job_id))

    assert result.successful()
    assert attempts == 1
    job = repository.get_job(job_id)
    assert job is not None
    assert job.status == JobStatus.FAILED
    assert [
        event.status for event in repository.list_events_after(job_id, 0)
    ].count(JobStatus.FAILED) == 1
    assert len(session_factory.sessions) == 1
    assert session_factory.sessions[0].closed is True


def test_process_job_retries_transient_session_factory_failure(
    monkeypatch,
    worker_storage,
    celery_eager,
) -> None:
    from text_verification.workers import tasks as worker_tasks
    from text_verification.workers.tasks import process_job

    repository = InMemoryJobRepository()
    job_id = _seed_txt_job(repository, worker_storage)
    session_factory = FlakySessionFactory(failures_remaining=1)
    verification_repository = InMemoryVerificationRepository()
    pipeline = build_default_verification_pipeline(Settings(llm_api_key=""))
    monkeypatch.setattr(worker_tasks, "SESSION_FACTORY_PROVIDER", lambda: session_factory)
    monkeypatch.setattr(worker_tasks, "STORAGE_FACTORY", lambda: worker_storage)
    monkeypatch.setattr(worker_tasks, "REPOSITORY_FACTORY", lambda session: repository)
    monkeypatch.setattr(
        worker_tasks,
        "VERIFICATION_REPOSITORY_FACTORY",
        lambda session: verification_repository,
    )
    monkeypatch.setattr(worker_tasks, "PIPELINE_FACTORY", lambda: pipeline)

    result = process_job.delay(str(job_id))

    assert result.successful()
    assert session_factory.calls == 2
    assert len(session_factory.sessions) == 1
    assert session_factory.sessions[0].closed is True
    assert repository.get_job(job_id).status == JobStatus.COMPLETED
    assert JobStatus.FAILED not in [
        event.status for event in repository.list_events_after(job_id, 0)
    ]


def test_process_job_rolls_back_and_retries_transient_database_failure(
    monkeypatch,
    worker_storage,
    celery_eager,
) -> None:
    from text_verification.workers.tasks import process_job

    repository = FlakyGetJobRepository()
    job_id = _seed_txt_job(repository, worker_storage)
    session_factory = _configure_worker_dependencies(
        monkeypatch,
        repository,
        worker_storage,
    )

    result = process_job.delay(str(job_id))

    assert result.successful()
    assert repository.rollback_calls == 1
    assert repository.get_job(job_id).status == JobStatus.COMPLETED
    assert len(session_factory.sessions) == 2
    assert all(session.closed for session in session_factory.sessions)


def test_process_job_retry_configuration_is_bounded_and_late_acked() -> None:
    from text_verification.workers.tasks import process_job

    assert process_job.max_retries == 2
    assert process_job.acks_late is True
