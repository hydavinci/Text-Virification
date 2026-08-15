from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from text_verification.domain.documents import DocumentModel, FileType
from text_verification.domain.jobs import (
    TERMINAL_STATUSES,
    JobEvent,
    JobRead,
    JobStatus,
    TerminalJobStateError,
)
from text_verification.infrastructure.storage import InvalidUpload, JobStorage


class InMemoryJobRepository:
    def __init__(self, *, fail_on_commit_calls: set[int] | None = None) -> None:
        self._fail_on_commit_calls = fail_on_commit_calls or set()
        self._commit_count = 0
        self.rollback_calls = 0
        self._transaction_observers: list[object] = []
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

    def register_transaction_observer(self, observer: object) -> None:
        self._transaction_observers.append(observer)

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
        for observer in self._transaction_observers:
            observer.commit()
        self._reset_working_copy()

    def rollback(self) -> None:
        self.rollback_calls += 1
        for observer in self._transaction_observers:
            observer.rollback()
        self._reset_working_copy()

    def _reset_working_copy(self) -> None:
        self._working_jobs = {
            job_id: job.model_copy(deep=True) for job_id, job in self._jobs.items()
        }
        self._working_events = {
            job_id: [event for event in events] for job_id, events in self._events.items()
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


class FlakyGetJobRepository(InMemoryJobRepository):
    def __init__(self) -> None:
        super().__init__()
        self.failures_remaining = 1

    def get_job(self, job_id: UUID) -> JobRead | None:
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise RuntimeError("database unavailable")
        return super().get_job(job_id)


class InMemoryAnalysisRepository:
    def __init__(self, repository: InMemoryJobRepository) -> None:
        repository.register_transaction_observer(self)
        self._documents: dict[UUID, DocumentModel] = {}
        self._issues: dict[UUID, list[object]] = {}
        self._failures: dict[UUID, dict[object, object]] = {}
        self._last_job_id: UUID | None = None
        self._working_last_job_id: UUID | None = None
        self._reset_working_copy()

    def replace_analysis(self, job_id, document, issues, failures) -> None:
        self._working_documents[job_id] = document.model_copy(deep=True)
        self._working_issues[job_id] = [issue.model_copy(deep=True) for issue in issues]
        self._working_failures[job_id] = dict(failures)
        self._working_last_job_id = job_id

    def get_document(self, job_id: UUID) -> DocumentModel | None:
        document = self._documents.get(job_id)
        if document is None:
            return None
        return document.model_copy(deep=True)

    @property
    def issues(self) -> list[object]:
        if self._last_job_id is None:
            return []
        return [issue.model_copy(deep=True) for issue in self._issues.get(self._last_job_id, [])]

    @property
    def failures(self) -> dict[object, object]:
        if self._last_job_id is None:
            return {}
        return dict(self._failures.get(self._last_job_id, {}))

    def commit(self) -> None:
        self._documents = {
            job_id: document.model_copy(deep=True)
            for job_id, document in self._working_documents.items()
        }
        self._issues = {
            job_id: [issue.model_copy(deep=True) for issue in issues]
            for job_id, issues in self._working_issues.items()
        }
        self._failures = {
            job_id: dict(failures) for job_id, failures in self._working_failures.items()
        }
        self._last_job_id = self._working_last_job_id
        self._reset_working_copy()

    def rollback(self) -> None:
        self._reset_working_copy()

    def _reset_working_copy(self) -> None:
        self._working_documents = {
            job_id: document.model_copy(deep=True)
            for job_id, document in self._documents.items()
        }
        self._working_issues = {
            job_id: [issue.model_copy(deep=True) for issue in issues]
            for job_id, issues in self._issues.items()
        }
        self._working_failures = {
            job_id: dict(failures) for job_id, failures in self._failures.items()
        }
        self._working_last_job_id = self._last_job_id


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
class ExplodingChecker:
    error: Exception

    name: str = "explode"
    version: str = "1"
    supported_languages: set[str] = field(default_factory=lambda: {"zh-CN"})

    def check(self, document, context):
        del document, context
        raise self.error


@dataclass
class FlakyRunnerFactory:
    failures_remaining: int
    attempts: int = 0

    def __call__(self, session, repository, storage):
        del session
        self.attempts += 1
        if self.failures_remaining:
            self.failures_remaining -= 1
            return ExplodingRunner(RuntimeError("transient parser failure"))
        return _build_in_memory_runner_factory(InMemoryAnalysisRepository(repository))(
            None,
            repository,
            storage,
        )


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
    text: str | bytes = "需要检查",
) -> UUID:
    job_id = uuid4()
    created_at = datetime.now(UTC)
    size_bytes = 8

    if persist_source:
        payload = text.encode("utf-8") if isinstance(text, str) else text
        stored = storage.save_bytes(job_id, "sample.txt", payload)
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
    monkeypatch.setattr(
        worker_tasks,
        "RUNNER_FACTORY",
        runner_factory
        or _build_in_memory_runner_factory(InMemoryAnalysisRepository(repository)),
    )
    return session_factory


def _build_parser_registry():
    from text_verification.parsers import DocxParser, ParserRegistry, PdfParser, TxtParser

    return ParserRegistry((TxtParser(), PdfParser(), DocxParser()))


def _build_real_checker_registry():
    from text_verification.checkers import CheckerRegistry, RuleLoader

    repository_root = Path(__file__).resolve().parents[4]
    rule_set = RuleLoader(
        repository_root / "resources" / "rules" / "common-rules.zh-cn.json",
        repository_root / "resources" / "rules" / "scenarios.zh-cn.json",
    ).load()
    return CheckerRegistry.from_rule_set(rule_set)


def checker_registry_with_failure(failing_category):
    from collections import defaultdict

    from text_verification.checkers import CheckerRegistry, RuleChecker, RuleLoader

    repository_root = Path(__file__).resolve().parents[4]
    rule_set = RuleLoader(
        repository_root / "resources" / "rules" / "common-rules.zh-cn.json",
        repository_root / "resources" / "rules" / "scenarios.zh-cn.json",
    ).load()
    grouped = defaultdict(list)
    for rule in rule_set.rules:
        if rule.category == failing_category:
            grouped[rule.category].append(ExplodingChecker(RuntimeError("checker offline")))
            continue
        grouped[rule.category].append(
            RuleChecker(rule, source="local_rules", source_version=rule_set.version)
        )
    return CheckerRegistry(grouped)


def _build_in_memory_runner_factory(
    analysis_repository: InMemoryAnalysisRepository,
    *,
    checker_registry=None,
):
    parsers = _build_parser_registry()
    checkers = checker_registry or _build_real_checker_registry()

    def runner_factory(session, repository, storage):
        del session
        from text_verification.workers.pipeline import PipelineRunner

        return PipelineRunner(repository, analysis_repository, storage, parsers, checkers)

    return runner_factory


def configure_real_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    repository: InMemoryJobRepository,
    analysis_repository: InMemoryAnalysisRepository,
    storage: JobStorage,
    *,
    checker_registry=None,
) -> SessionFactorySpy:
    return _configure_worker_dependencies(
        monkeypatch,
        repository,
        storage,
        runner_factory=_build_in_memory_runner_factory(
            analysis_repository,
            checker_registry=checker_registry,
        ),
    )


def test_process_job_persists_analysis_and_completes(
    monkeypatch,
    worker_storage,
    celery_eager,
) -> None:
    from text_verification.workers.tasks import process_job

    repository = InMemoryJobRepository()
    analysis_repository = InMemoryAnalysisRepository(repository)
    job_id = _seed_txt_job(repository, worker_storage, text="这是绝对领先的方案")
    session_factory = configure_real_pipeline(
        monkeypatch,
        repository,
        analysis_repository,
        worker_storage,
    )

    result = process_job.delay(str(job_id))

    assert result.successful()
    job = repository.get_job(job_id)
    assert job is not None
    assert job.status == JobStatus.COMPLETED
    assert job.progress == 100
    assert analysis_repository.get_document(job_id) is not None
    assert [issue.rule_id for issue in analysis_repository.issues] == ["security-ad-001"]
    assert [event.status for event in repository.list_events_after(job_id, 0)] == [
        JobStatus.QUEUED,
        JobStatus.UPLOAD_VALIDATED,
        JobStatus.PARSING,
        JobStatus.COMPLETED,
    ]
    assert len(session_factory.sessions) == 1
    assert session_factory.sessions[0].closed is True


def test_process_job_marks_partial_and_keeps_available_issues(
    monkeypatch,
    worker_storage,
    celery_eager,
) -> None:
    from text_verification.checkers import CheckCategory
    from text_verification.workers.tasks import process_job

    repository = InMemoryJobRepository()
    analysis_repository = InMemoryAnalysisRepository(repository)
    job_id = _seed_txt_job(repository, worker_storage, text="祕密且绝对领先")
    session_factory = configure_real_pipeline(
        monkeypatch,
        repository,
        analysis_repository,
        worker_storage,
        checker_registry=checker_registry_with_failure(CheckCategory.SECURITY),
    )

    result = process_job.delay(str(job_id))

    assert result.successful()
    job = repository.get_job(job_id)
    assert job is not None
    assert job.status == JobStatus.PARTIAL
    assert [issue.rule_id for issue in analysis_repository.issues] == [
        "character-simplified-001"
    ]
    assert analysis_repository.failures[CheckCategory.SECURITY].code == "checker_failed"
    assert [event.status for event in repository.list_events_after(job_id, 0)] == [
        JobStatus.QUEUED,
        JobStatus.UPLOAD_VALIDATED,
        JobStatus.PARSING,
        JobStatus.PARTIAL,
    ]
    assert len(session_factory.sessions) == 1
    assert session_factory.sessions[0].closed is True


def test_process_job_parser_errors_fail_without_retry_and_keep_public_message(
    monkeypatch,
    worker_storage,
    celery_eager,
) -> None:
    from text_verification.workers.tasks import process_job

    repository = InMemoryJobRepository()
    analysis_repository = InMemoryAnalysisRepository(repository)
    job_id = _seed_txt_job(repository, worker_storage, text="需要检查".encode("utf-16"))
    session_factory = configure_real_pipeline(
        monkeypatch,
        repository,
        analysis_repository,
        worker_storage,
    )

    result = process_job.delay(str(job_id))

    assert result.successful()
    job = repository.get_job(job_id)
    assert job is not None
    assert job.status == JobStatus.FAILED
    assert job.error_code == "txt_binary_content"
    assert job.error_message == "无法解析文本文件。"
    assert analysis_repository.get_document(job_id) is None
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

    def invalid_runner_factory(session, repository, storage):
        del session, repository, storage
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
    monkeypatch.setattr(worker_tasks, "SESSION_FACTORY_PROVIDER", lambda: session_factory)
    monkeypatch.setattr(worker_tasks, "STORAGE_FACTORY", lambda: worker_storage)
    monkeypatch.setattr(worker_tasks, "REPOSITORY_FACTORY", lambda session: repository)
    monkeypatch.setattr(
        worker_tasks,
        "RUNNER_FACTORY",
        _build_in_memory_runner_factory(InMemoryAnalysisRepository(repository)),
    )

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
