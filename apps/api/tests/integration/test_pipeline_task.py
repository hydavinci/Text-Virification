from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

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
    JobClaimDisposition,
    JobClaimResult,
    JobEvent,
    JobLeaseLostError,
    JobRead,
    JobRecoveryClaim,
    JobRecoveryKind,
    JobStateConflictError,
    JobStatus,
    JobUnleasedError,
    TerminalJobStateError,
)
from text_verification.domain.ports import VerificationProgressObserver
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
        fail_completed_commit_once: bool = False,
    ) -> None:
        self._fail_on_commit_calls = fail_on_commit_calls or set()
        self._operations = operations
        self._fail_completed_commit_once = fail_completed_commit_once
        self._has_result = lambda job_id: False
        self.claim_owners: list[UUID] = []
        self.claim_predecessors: list[UUID | None] = []
        self._commit_count = 0
        self.rollback_calls = 0
        self._jobs: dict[UUID, JobRead] = {}
        self._events: dict[UUID, list[JobEvent]] = {}
        self._leases: dict[UUID, tuple[UUID, datetime] | None] = {}
        self._rescue_due_at: dict[UUID, datetime] = {}
        self._rescue_attempts: dict[UUID, int] = {}
        self._rescue_last_published_at: dict[UUID, datetime | None] = {}
        self._reset_working_copy()

    def bind_result_checker(self, has_result) -> None:
        self._has_result = has_result

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
        self._working_leases[job_id] = None
        self._working_rescue_due_at[job_id] = created_at + timedelta(minutes=2)
        self._working_rescue_attempts[job_id] = 0
        self._working_rescue_last_published_at[job_id] = None
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

    def acquire_lease(
        self,
        job_id: UUID,
        *,
        owner_token: UUID,
        now: datetime,
        lease_expires_at: datetime,
        previous_owner_token: UUID | None = None,
    ) -> JobClaimResult:
        self.claim_owners.append(owner_token)
        self.claim_predecessors.append(previous_owner_token)
        job = self._working_jobs.get(job_id)
        if job is None:
            return JobClaimResult(JobClaimDisposition.MISSING, None)
        if job.status in TERMINAL_STATUSES:
            return JobClaimResult(JobClaimDisposition.TERMINAL, job)
        lease = self._working_leases[job_id]
        can_rotate = (
            previous_owner_token is not None
            and lease is not None
            and lease[0] == previous_owner_token
            and lease[1] > now
        )
        can_start = job.expires_at > now and (lease is None or lease[1] <= now)
        if not can_start and not can_rotate:
            if job.expires_at <= now:
                return JobClaimResult(
                    JobClaimDisposition.RETENTION_EXPIRED,
                    job,
                    None if lease is None else lease[1],
                )
            return JobClaimResult(JobClaimDisposition.LEASED, job, lease[1])
        self._working_leases[job_id] = (owner_token, lease_expires_at)
        self._working_rescue_due_at[job_id] = lease_expires_at
        self._working_rescue_last_published_at[job_id] = None
        return JobClaimResult(
            JobClaimDisposition.ACQUIRED,
            job,
            lease_expires_at,
        )

    def claim_due_recoveries(
        self,
        *,
        now: datetime,
        publication_due_at: datetime,
        limit: int,
    ) -> list[JobRecoveryClaim]:
        claims: list[JobRecoveryClaim] = []
        for job_id, job in sorted(self._working_jobs.items(), key=lambda item: str(item[0])):
            if len(claims) >= limit:
                break
            if job.status in TERMINAL_STATUSES or job.expires_at <= now:
                continue
            if self._working_rescue_due_at[job_id] > now:
                continue
            if self._working_rescue_last_published_at[job_id] is not None:
                continue
            lease = self._working_leases[job_id]
            if lease is not None and lease[1] > now:
                continue
            self._working_rescue_attempts[job_id] += 1
            self._working_rescue_due_at[job_id] = publication_due_at
            claims.append(
                JobRecoveryClaim(
                    kind=(
                        JobRecoveryKind.INITIAL_DISPATCH
                        if lease is None
                        else JobRecoveryKind.EXPIRED_LEASE
                    ),
                    job=job,
                    attempt=self._working_rescue_attempts[job_id],
                    publication_due_at=publication_due_at,
                )
            )
        return claims

    def mark_recovery_published(
        self,
        job_id: UUID,
        *,
        attempt: int,
        published_at: datetime,
    ) -> bool:
        if (
            self._working_rescue_attempts.get(job_id) != attempt
            or self._working_rescue_last_published_at.get(job_id) is not None
        ):
            return False
        self._working_rescue_last_published_at[job_id] = published_at
        return True

    def mark_recovery_publish_failed(
        self,
        job_id: UUID,
        *,
        attempt: int,
        now: datetime,
        retry_due_at: datetime,
    ) -> bool:
        job = self._working_jobs.get(job_id)
        lease = self._working_leases.get(job_id)
        if (
            job is None
            or self._working_rescue_attempts.get(job_id) != attempt
            or job.status in TERMINAL_STATUSES
            or job.expires_at <= now
            or (lease is not None and lease[1] > now)
        ):
            return False
        self._working_rescue_due_at[job_id] = retry_due_at
        self._working_rescue_last_published_at[job_id] = None
        return True

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
        if status in TERMINAL_STATUSES:
            self._working_leases[job_id] = None
        self._working_events[job_id].append(
            JobEvent(
                sequence=len(self._working_events[job_id]) + 1,
                status=status,
                progress=progress,
                message=message,
                created_at=datetime.now(UTC),
            )
        )

    def transition_claimed(
        self,
        job_id: UUID,
        *,
        owner_token: UUID,
        expected_status: JobStatus,
        status: JobStatus,
        progress: int,
        message: str,
        now: datetime,
        lease_expires_at: datetime,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> JobRead:
        expected_next = {
            JobStatus.QUEUED: JobStatus.UPLOAD_VALIDATED,
            JobStatus.UPLOAD_VALIDATED: JobStatus.PARSING,
            JobStatus.PARSING: JobStatus.CHECKING_FORMAT,
            JobStatus.CHECKING_FORMAT: JobStatus.CHECKING_SENSITIVE,
            JobStatus.CHECKING_SENSITIVE: JobStatus.CHECKING_CHINESE,
            JobStatus.CHECKING_CHINESE: JobStatus.CHECKING_ENGLISH,
        }
        if expected_next.get(expected_status) is not status:
            raise ValueError("Invalid claimed job transition")
        self._assert_claim(job_id, owner_token, now)
        self._assert_status(job_id, expected_status)
        self.transition(
            job_id,
            status,
            progress,
            message,
            error_code=error_code,
            error_message=error_message,
        )
        self._working_leases[job_id] = (owner_token, lease_expires_at)
        self._working_rescue_due_at[job_id] = lease_expires_at
        self._working_rescue_last_published_at[job_id] = None
        return self._working_jobs[job_id]

    def fail_claimed_job(
        self,
        job_id: UUID,
        *,
        owner_token: UUID,
        expected_status: JobStatus,
        progress: int,
        message: str,
        error_code: str,
        error_message: str,
        now: datetime,
    ) -> bool:
        self._assert_claim(job_id, owner_token, now)
        self._assert_status(job_id, expected_status)
        if self._has_result(job_id):
            return False
        self.transition(
            job_id,
            JobStatus.FAILED,
            progress,
            message,
            error_code=error_code,
            error_message=error_message,
        )
        return True

    def complete_claimed_job(
        self,
        job_id: UUID,
        *,
        owner_token: UUID,
        expected_status: JobStatus,
        progress: int,
        message: str,
        now: datetime,
    ) -> JobRead:
        if expected_status is not JobStatus.CHECKING_ENGLISH:
            raise ValueError("completed jobs must advance from checking_english")
        self._assert_claim(job_id, owner_token, now)
        self._assert_status(job_id, expected_status)
        if not self._has_result(job_id):
            raise ValueError("result is required")
        self.transition(job_id, JobStatus.COMPLETED, progress, message)
        return self._working_jobs[job_id]

    def force_lease(
        self,
        job_id: UUID,
        owner_token: UUID,
        lease_expires_at: datetime,
    ) -> None:
        self._leases[job_id] = (owner_token, lease_expires_at)
        self._rescue_due_at[job_id] = lease_expires_at
        self._reset_working_copy()

    def list_events_after(self, job_id: UUID, after_sequence: int) -> list[JobEvent]:
        return [
            event for event in self._events.get(job_id, []) if event.sequence > after_sequence
        ]

    def commit(self) -> None:
        self._commit_count += 1
        if self._commit_count in self._fail_on_commit_calls:
            raise RuntimeError("database unavailable")
        if self._fail_completed_commit_once and any(
            job.status is JobStatus.COMPLETED
            and self._jobs[job_id].status is not JobStatus.COMPLETED
            for job_id, job in self._working_jobs.items()
        ):
            self._fail_completed_commit_once = False
            raise RuntimeError("completion commit failed")
        self._jobs = {
            job_id: job.model_copy(deep=True) for job_id, job in self._working_jobs.items()
        }
        self._events = {
            job_id: [event for event in events] for job_id, events in self._working_events.items()
        }
        self._leases = dict(self._working_leases)
        self._rescue_due_at = dict(self._working_rescue_due_at)
        self._rescue_attempts = dict(self._working_rescue_attempts)
        self._rescue_last_published_at = dict(
            self._working_rescue_last_published_at
        )
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
        self._working_leases = dict(self._leases)
        self._working_rescue_due_at = dict(self._rescue_due_at)
        self._working_rescue_attempts = dict(self._rescue_attempts)
        self._working_rescue_last_published_at = dict(
            self._rescue_last_published_at
        )

    def _assert_claim(self, job_id: UUID, owner_token: UUID, now: datetime) -> None:
        lease = self._working_leases.get(job_id)
        if lease is None:
            raise JobUnleasedError(job_id)
        if lease[0] != owner_token or lease[1] <= now:
            raise JobLeaseLostError(job_id, lease[1])

    def _assert_status(self, job_id: UUID, expected_status: JobStatus) -> None:
        current_status = self._working_jobs[job_id].status
        if current_status is not expected_status:
            raise JobStateConflictError(
                job_id=job_id,
                expected_status=expected_status,
                current_status=current_status,
            )


class InMemoryVerificationRepository:
    def __init__(self, *, operations: list[str] | None = None) -> None:
        self._operations = operations
        self.rollback_calls = 0
        self._results: dict[UUID, VerificationResult] = {}
        self._working_results: dict[UUID, VerificationResult] = {}
        self._jobs: InMemoryJobRepository | None = None

    def bind_jobs(self, repository: InMemoryJobRepository) -> None:
        self._jobs = repository

    def has_result(self, job_id: UUID) -> bool:
        return job_id in self._results

    def save_result(self, job_id: UUID, result: VerificationResult) -> None:
        existing = self._working_results.get(job_id)
        if existing is not None and existing != result:
            raise ValueError(f"Job {job_id} already has a different result.")
        self._working_results[job_id] = result.model_copy(deep=True)

    def get_result_for_job(self, job_id: UUID) -> VerificationResult | None:
        result = self._results.get(job_id)
        return None if result is None else result.model_copy(deep=True)

    def get_result_for_claimed_job(
        self,
        job_id: UUID,
        *,
        owner_token: UUID,
        now: datetime,
    ) -> VerificationResult | None:
        self._assert_claim(job_id, owner_token, now)
        return self.get_result_for_job(job_id)

    def save_claimed_result(
        self,
        job_id: UUID,
        result: VerificationResult,
        *,
        owner_token: UUID,
        expected_status: JobStatus,
        now: datetime,
    ) -> None:
        if expected_status is not JobStatus.CHECKING_ENGLISH:
            raise ValueError("claimed results require checking_english")
        self._assert_claim(job_id, owner_token, now)
        if self._jobs is None:
            raise AssertionError("job repository is not bound")
        job = self._jobs._working_jobs[job_id]
        if job.status is not expected_status:
            raise JobStateConflictError(
                job_id=job_id,
                expected_status=expected_status,
                current_status=job.status,
            )
        self.save_result(job_id, result)

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

    def _assert_claim(self, job_id: UUID, owner_token: UUID, now: datetime) -> None:
        if self._jobs is None:
            raise AssertionError("job repository is not bound")
        self._jobs._assert_claim(job_id, owner_token, now)


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

    def acquire_lease(
        self,
        job_id: UUID,
        *,
        owner_token: UUID,
        now: datetime,
        lease_expires_at: datetime,
        previous_owner_token: UUID | None = None,
    ) -> JobClaimResult:
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise RuntimeError("database unavailable")
        return super().acquire_lease(
            job_id,
            owner_token=owner_token,
            now=now,
            lease_expires_at=lease_expires_at,
            previous_owner_token=previous_owner_token,
        )


@dataclass
class FakeSession:
    closed: bool = False
    owner: SessionFactorySpy | None = None

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.owner is not None:
            self.owner.active_sessions -= 1


@dataclass
class SessionFactorySpy:
    sessions: list[FakeSession] = field(default_factory=list)
    active_sessions: int = 0

    def __call__(self) -> FakeSession:
        self.active_sessions += 1
        session = FakeSession(owner=self)
        self.sessions.append(session)
        return session


@dataclass
class ExplodingRunner:
    error: Exception

    def run(
        self,
        job: JobRead,
        progress_observer: VerificationProgressObserver,
    ) -> None:
        del job, progress_observer
        raise self.error


@dataclass
class FlakyRunnerFactory:
    failures_remaining: int
    attempts: int = 0

    def __call__(self, storage, pipeline):
        from text_verification.workers.pipeline import PipelineRunner

        self.attempts += 1
        if self.failures_remaining:
            self.failures_remaining -= 1
            return ExplodingRunner(RuntimeError("transient parser failure"))
        return PipelineRunner(storage, pipeline)


@dataclass
class RecordingPipeline:
    delegate: VerificationPipeline
    commands: list[VerificationCommand] = field(default_factory=list)

    def run(
        self,
        command: VerificationCommand,
        *,
        progress_observer: VerificationProgressObserver | None = None,
    ) -> VerificationResult:
        self.commands.append(command)
        return self.delegate.run(command, progress_observer=progress_observer)


@dataclass
class FlakyVerificationPipeline:
    delegate: VerificationPipeline
    error: VerificationError
    failures_remaining: int
    attempts: int = 0

    def run(
        self,
        command: VerificationCommand,
        *,
        progress_observer: VerificationProgressObserver | None = None,
    ) -> VerificationResult:
        self.attempts += 1
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise self.error
        return self.delegate.run(command, progress_observer=progress_observer)


@dataclass
class SessionBoundaryPipeline:
    delegate: VerificationPipeline
    sessions: SessionFactorySpy
    calls: int = 0

    def run(
        self,
        command: VerificationCommand,
        *,
        progress_observer: VerificationProgressObserver | None = None,
    ) -> VerificationResult:
        assert self.sessions.active_sessions == 0
        self.calls += 1

        def observe(stage) -> None:
            assert self.sessions.active_sessions == 0
            if progress_observer is not None:
                progress_observer(stage)
            assert self.sessions.active_sessions == 0

        result = self.delegate.run(command, progress_observer=observe)
        assert self.sessions.active_sessions == 0
        return result


@dataclass
class LeaseLosingPipeline:
    repository: InMemoryJobRepository
    replacement_owner: UUID
    replacement_expires_at: datetime | None = None

    def run(
        self,
        command: VerificationCommand,
        *,
        progress_observer: VerificationProgressObserver | None = None,
    ) -> VerificationResult:
        if progress_observer is not None:
            from text_verification.domain.ports import VerificationProgressStage

            progress_observer(VerificationProgressStage.PARSING)
        self.repository.force_lease(
            command.document_id,
            self.replacement_owner,
            self.replacement_expires_at
            or datetime.now(UTC) + timedelta(minutes=20),
        )
        raise VerificationError(
            "parser_failed",
            "parsing",
            "The source document could not be parsed.",
            False,
        )


@dataclass
class SilentProgressPipeline:
    delegate: VerificationPipeline

    def run(
        self,
        command: VerificationCommand,
        *,
        progress_observer: VerificationProgressObserver | None = None,
    ) -> VerificationResult:
        del progress_observer
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


@dataclass
class FakeTaskRequest:
    retries: int = 0


@dataclass
class FakeBoundTask:
    request: FakeTaskRequest = field(default_factory=FakeTaskRequest)

    def retry(self, **kwargs):
        raise AssertionError(f"failure retry must not be used for lease rescue: {kwargs}")


@dataclass
class MutableClock:
    current: datetime

    def __call__(self) -> datetime:
        return self.current


@dataclass
class CapturedCeleryMessage:
    task_module: object
    args: tuple[str, ...]
    kwargs: dict[str, str]
    countdown: int | None

    def run(self) -> None:
        self.task_module._process_job(  # type: ignore[attr-defined]
            FakeBoundTask(),
            *self.args,
            **self.kwargs,
        )


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
    created_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> UUID:
    job_id = uuid4()
    resolved_created_at = created_at or datetime.now(UTC)
    resolved_expires_at = expires_at or resolved_created_at + timedelta(hours=24)
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
        created_at=resolved_created_at,
        expires_at=resolved_expires_at,
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
    session_factory: SessionFactorySpy | None = None,
) -> SessionFactorySpy:
    from text_verification.workers import tasks as worker_tasks

    session_factory = session_factory or SessionFactorySpy()
    verification_repository = verification_repository or InMemoryVerificationRepository()
    pipeline = pipeline or build_default_verification_pipeline(Settings(llm_api_key=""))
    verification_repository.bind_jobs(repository)
    repository.bind_result_checker(verification_repository.has_result)
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
    assert len(session_factory.sessions) > 1
    assert all(session.closed for session in session_factory.sessions)


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
    db_session_factory,
    worker_storage: JobStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from text_verification.workers import tasks as worker_tasks
    from text_verification.workers.tasks import (
        ProcessAttemptDisposition,
        _run_process_job_attempt,
    )

    job_id = uuid4()
    created_at = datetime.now(UTC)
    stored = worker_storage.save_bytes(job_id, "sample.txt", "需要检查".encode())
    seed_session = db_session_factory()
    try:
        repository = SqlJobRepository(seed_session)
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
    finally:
        seed_session.close()
    monkeypatch.setattr(worker_tasks, "SESSION_FACTORY_PROVIDER", lambda: db_session_factory)
    monkeypatch.setattr(worker_tasks, "STORAGE_FACTORY", lambda: worker_storage)
    monkeypatch.setattr(
        worker_tasks,
        "PIPELINE_FACTORY",
        lambda: build_default_verification_pipeline(Settings(llm_api_key="")),
    )

    outcome = _run_process_job_attempt(job_id, uuid4())

    verification_session = db_session_factory()
    try:
        repository = SqlJobRepository(verification_session)
        result = VerificationRepository(verification_session).get_result_for_job(job_id)
        job = repository.get_job(job_id)
    finally:
        verification_session.close()

    assert outcome.disposition is ProcessAttemptDisposition.PROCESSED
    assert result is not None
    assert result.document_id == job_id
    assert result.source_name == "sample.txt"
    assert result.execution_mode is VerificationExecutionMode.ASYNCHRONOUS
    assert job is not None
    assert job.status is JobStatus.COMPLETED


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
    assert len(session_factory.sessions) > 1
    job = repository.get_job(job_id)
    assert job is not None
    assert job.status is JobStatus.FAILED
    assert job.error_code == "parser_failed"
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
    assert len(session_factory.sessions) > 2
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

    repository = InMemoryJobRepository(fail_completed_commit_once=True)
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
    assert len(session_factory.sessions) > 2
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
    assert len(session_factory.sessions) > 2
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
    assert len(session_factory.sessions) > 4
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

    def invalid_runner_factory(storage, pipeline):
        del storage, pipeline
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
    assert len(session_factory.sessions) > 1
    assert all(session.closed for session in session_factory.sessions)


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
    verification_repository.bind_jobs(repository)
    repository.bind_result_checker(verification_repository.has_result)
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
    assert session_factory.calls == len(session_factory.sessions) + 1
    assert len(session_factory.sessions) > 1
    assert all(session.closed for session in session_factory.sessions)
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
    assert len(session_factory.sessions) > 2
    assert all(session.closed for session in session_factory.sessions)


def test_process_job_retry_configuration_is_bounded_and_late_acked() -> None:
    from text_verification.workers.tasks import process_job

    assert process_job.max_retries == 2
    assert process_job.acks_late is True


def test_duplicate_delivery_with_live_lease_is_explicit_noop(
    monkeypatch,
    worker_storage,
) -> None:
    from text_verification.workers.tasks import (
        ProcessAttemptDisposition,
        _run_process_job_attempt,
    )

    repository = InMemoryJobRepository()
    verification_repository = InMemoryVerificationRepository()
    pipeline = RecordingPipeline(
        build_default_verification_pipeline(Settings(llm_api_key=""))
    )
    job_id = _seed_txt_job(repository, worker_storage)
    lease_expires_at = datetime.now(UTC) + timedelta(minutes=20)
    repository.force_lease(
        job_id,
        uuid4(),
        lease_expires_at,
    )
    _configure_worker_dependencies(
        monkeypatch,
        repository,
        worker_storage,
        verification_repository=verification_repository,
        pipeline=pipeline,
    )

    outcome = _run_process_job_attempt(job_id, uuid4())

    assert outcome.disposition is ProcessAttemptDisposition.DUPLICATE
    assert outcome.retry_at == lease_expires_at
    assert pipeline.commands == []
    assert repository.get_job(job_id).status is JobStatus.QUEUED
    assert [event.status for event in repository.list_events_after(job_id, 0)] == [
        JobStatus.QUEUED
    ]


def test_expired_lease_is_reclaimed_and_resumes_without_duplicate_events(
    monkeypatch,
    worker_storage,
) -> None:
    from text_verification.workers.tasks import (
        ProcessAttemptDisposition,
        _run_process_job_attempt,
    )

    repository = InMemoryJobRepository()
    verification_repository = InMemoryVerificationRepository()
    pipeline = RecordingPipeline(
        build_default_verification_pipeline(Settings(llm_api_key=""))
    )
    job_id = _seed_txt_job(repository, worker_storage)
    repository.transition(job_id, JobStatus.UPLOAD_VALIDATED, 10, "上传校验完成")
    repository.transition(job_id, JobStatus.PARSING, 25, "开始解析")
    repository.transition(job_id, JobStatus.CHECKING_FORMAT, 50, "正在检查格式")
    repository.transition(job_id, JobStatus.CHECKING_SENSITIVE, 65, "正在检查敏感词")
    repository.commit()
    repository.force_lease(
        job_id,
        uuid4(),
        datetime.now(UTC) - timedelta(seconds=1),
    )
    _configure_worker_dependencies(
        monkeypatch,
        repository,
        worker_storage,
        verification_repository=verification_repository,
        pipeline=pipeline,
    )

    outcome = _run_process_job_attempt(job_id, uuid4())

    assert outcome.disposition is ProcessAttemptDisposition.PROCESSED
    assert len(pipeline.commands) == 1
    assert [
        event.status for event in repository.list_events_after(job_id, 0)
    ] == COMPLETED_STATUS_SEQUENCE


def test_worker_holds_no_database_session_while_pipeline_runs(
    monkeypatch,
    worker_storage,
    celery_eager,
) -> None:
    from text_verification.workers.tasks import process_job

    repository = InMemoryJobRepository()
    verification_repository = InMemoryVerificationRepository()
    sessions = SessionFactorySpy()
    pipeline = SessionBoundaryPipeline(
        build_default_verification_pipeline(Settings(llm_api_key="")),
        sessions,
    )
    job_id = _seed_txt_job(repository, worker_storage)
    _configure_worker_dependencies(
        monkeypatch,
        repository,
        worker_storage,
        verification_repository=verification_repository,
        pipeline=pipeline,
        session_factory=sessions,
    )

    result = process_job.delay(str(job_id))

    assert result.successful()
    assert pipeline.calls == 1
    assert sessions.active_sessions == 0
    assert all(session.closed for session in sessions.sessions)


def test_result_commit_before_completion_failure_retries_without_rerunning_pipeline(
    monkeypatch,
    worker_storage,
    celery_eager,
) -> None:
    from text_verification.workers.tasks import process_job

    repository = InMemoryJobRepository(fail_completed_commit_once=True)
    verification_repository = InMemoryVerificationRepository()
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
    assert len(pipeline.commands) == 1
    assert verification_repository.get_result_for_job(job_id) is not None
    assert repository.get_job(job_id).status is JobStatus.COMPLETED
    assert len(repository.claim_owners) >= 2
    assert len(set(repository.claim_owners)) == len(repository.claim_owners)
    assert repository.claim_predecessors[0] is None
    assert repository.claim_predecessors[1] == repository.claim_owners[0]
    assert JobStatus.FAILED not in [
        event.status for event in repository.list_events_after(job_id, 0)
    ]


def test_expected_failure_after_lease_loss_does_not_mutate_job(
    monkeypatch,
    worker_storage,
) -> None:
    from text_verification.workers.tasks import (
        ProcessAttemptDisposition,
        _run_process_job_attempt,
    )

    repository = InMemoryJobRepository()
    verification_repository = InMemoryVerificationRepository()
    job_id = _seed_txt_job(repository, worker_storage)
    _configure_worker_dependencies(
        monkeypatch,
        repository,
        worker_storage,
        verification_repository=verification_repository,
        pipeline=LeaseLosingPipeline(repository, uuid4()),
    )

    outcome = _run_process_job_attempt(job_id, uuid4())

    assert outcome.disposition is ProcessAttemptDisposition.LEASE_LOST
    assert repository.get_job(job_id).status is JobStatus.PARSING
    assert JobStatus.FAILED not in [
        event.status for event in repository.list_events_after(job_id, 0)
    ]


def test_worker_rejects_result_persistence_before_final_progress_stage(
    monkeypatch,
    worker_storage,
    celery_eager,
) -> None:
    from text_verification.workers.tasks import process_job

    repository = InMemoryJobRepository()
    verification_repository = InMemoryVerificationRepository()
    job_id = _seed_txt_job(repository, worker_storage)
    _configure_worker_dependencies(
        monkeypatch,
        repository,
        worker_storage,
        verification_repository=verification_repository,
        pipeline=SilentProgressPipeline(
            build_default_verification_pipeline(Settings(llm_api_key=""))
        ),
    )

    result = process_job.delay(str(job_id))

    assert result.failed()
    assert verification_repository.get_result_for_job(job_id) is None
    assert repository.get_job(job_id).status is JobStatus.FAILED


def test_owner_death_duplicate_schedules_fresh_message_at_lease_expiry_and_recovers(
    monkeypatch,
    worker_storage,
) -> None:
    from text_verification.workers import tasks as worker_tasks

    repository = InMemoryJobRepository()
    verification_repository = InMemoryVerificationRepository()
    pipeline = RecordingPipeline(
        build_default_verification_pipeline(Settings(llm_api_key=""))
    )
    job_id = _seed_txt_job(repository, worker_storage)
    now = datetime.now(UTC)
    lease_expires_at = now + timedelta(seconds=30)
    repository.force_lease(job_id, uuid4(), lease_expires_at)
    _configure_worker_dependencies(
        monkeypatch,
        repository,
        worker_storage,
        verification_repository=verification_repository,
        pipeline=pipeline,
    )
    clock = MutableClock(now)
    scheduled: list[CapturedCeleryMessage] = []
    monkeypatch.setattr(worker_tasks, "NOW_FACTORY", clock, raising=False)
    monkeypatch.setattr(
        worker_tasks.process_job,
        "apply_async",
        lambda args, countdown, kwargs=None: scheduled.append(
            CapturedCeleryMessage(
                worker_tasks,
                tuple(args),
                dict(kwargs or {}),
                countdown,
            )
        ),
    )

    worker_tasks._process_job(FakeBoundTask(), str(job_id))

    assert len(scheduled) == 1
    assert scheduled[0].args == (str(job_id),)
    assert scheduled[0].countdown == 30
    assert pipeline.commands == []

    clock.current = lease_expires_at + timedelta(seconds=1)
    scheduled[0].run()

    assert repository.get_job(job_id).status is JobStatus.COMPLETED
    assert len(pipeline.commands) == 1

    scheduled[0].run()

    assert len(scheduled) == 1
    assert len(pipeline.commands) == 1


def test_lease_lost_schedules_recovery_at_replacement_lease_expiry(
    monkeypatch,
    worker_storage,
) -> None:
    from text_verification.workers import tasks as worker_tasks

    repository = InMemoryJobRepository()
    verification_repository = InMemoryVerificationRepository()
    job_id = _seed_txt_job(repository, worker_storage)
    now = datetime.now(UTC)
    replacement_expires_at = now + timedelta(seconds=45)
    _configure_worker_dependencies(
        monkeypatch,
        repository,
        worker_storage,
        verification_repository=verification_repository,
        pipeline=LeaseLosingPipeline(
            repository,
            uuid4(),
            replacement_expires_at,
        ),
    )
    scheduled: list[tuple[str, int]] = []
    monkeypatch.setattr(worker_tasks, "NOW_FACTORY", MutableClock(now), raising=False)
    monkeypatch.setattr(
        worker_tasks,
        "RESCUE_SCHEDULER",
        lambda scheduled_job_id, countdown: scheduled.append(
            (scheduled_job_id, countdown)
        ),
        raising=False,
    )

    worker_tasks._process_job(FakeBoundTask(), str(job_id))

    assert scheduled == [(str(job_id), 45)]
    assert repository.get_job(job_id).status is JobStatus.PARSING
    assert JobStatus.FAILED not in [
        event.status for event in repository.list_events_after(job_id, 0)
    ]


def test_terminal_delivery_does_not_schedule_lease_rescue(
    monkeypatch,
    worker_storage,
) -> None:
    from text_verification.workers import tasks as worker_tasks

    repository = InMemoryJobRepository()
    job_id = _seed_txt_job(repository, worker_storage)
    repository.transition(job_id, JobStatus.COMPLETED, 100, "处理完成")
    repository.commit()
    _configure_worker_dependencies(monkeypatch, repository, worker_storage)
    scheduled: list[tuple[str, int]] = []
    monkeypatch.setattr(
        worker_tasks,
        "RESCUE_SCHEDULER",
        lambda scheduled_job_id, countdown: scheduled.append(
            (scheduled_job_id, countdown)
        ),
        raising=False,
    )

    worker_tasks._process_job(FakeBoundTask(), str(job_id))

    assert scheduled == []


def test_rescue_countdown_targets_expiry_and_is_nonnegative() -> None:
    from text_verification.workers.tasks import _rescue_countdown

    now = datetime(2026, 9, 1, 3, 0, 0, 100_000, tzinfo=UTC)

    assert _rescue_countdown(
        now + timedelta(seconds=4, microseconds=100_000),
        now=now,
    ) == 5
    assert _rescue_countdown(now - timedelta(seconds=1), now=now) == 0


def test_rescue_scheduler_starts_fresh_task_without_failure_retry_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from text_verification.workers import tasks as worker_tasks

    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        worker_tasks.process_job,
        "apply_async",
        lambda **kwargs: calls.append(kwargs),
    )

    worker_tasks._default_rescue_scheduler("job-id", 17)

    assert calls == [{"args": ("job-id",), "countdown": 17}]


def test_immediate_publish_failure_leaves_job_for_periodic_rescue(
    monkeypatch,
    worker_storage,
) -> None:
    from text_verification.workers import tasks as worker_tasks

    repository = InMemoryJobRepository()
    verification_repository = InMemoryVerificationRepository()
    pipeline = RecordingPipeline(
        build_default_verification_pipeline(Settings(llm_api_key=""))
    )
    job_id = _seed_txt_job(repository, worker_storage)
    now = datetime.now(UTC)
    lease_expires_at = now + timedelta(seconds=30)
    repository.force_lease(job_id, uuid4(), lease_expires_at)
    _configure_worker_dependencies(
        monkeypatch,
        repository,
        worker_storage,
        verification_repository=verification_repository,
        pipeline=pipeline,
    )
    clock = MutableClock(now)
    monkeypatch.setattr(worker_tasks, "NOW_FACTORY", clock)
    monkeypatch.setattr(
        worker_tasks.process_job,
        "apply_async",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("broker unavailable")),
    )

    worker_tasks._process_job(FakeBoundTask(), str(job_id))

    assert repository.get_job(job_id).status is JobStatus.QUEUED
    assert JobStatus.FAILED not in [
        event.status for event in repository.list_events_after(job_id, 0)
    ]

    captured: list[CapturedCeleryMessage] = []
    clock.current = lease_expires_at + timedelta(seconds=31)
    monkeypatch.setattr(
        worker_tasks.process_job,
        "apply_async",
        lambda args, kwargs=None, countdown=None: captured.append(
            CapturedCeleryMessage(
                worker_tasks,
                tuple(args),
                dict(kwargs or {}),
                countdown,
            )
        ),
    )

    rescued = worker_tasks._rescue_expired_job_leases()

    assert rescued == [str(job_id)]
    assert len(captured) == 1
    assert captured[0].kwargs == {}

    captured[0].run()

    assert repository.get_job(job_id).status is JobStatus.COMPLETED
    assert len(pipeline.commands) == 1


def test_retention_expired_delivery_does_not_run_or_schedule_recovery(
    monkeypatch: pytest.MonkeyPatch,
    worker_storage: JobStorage,
) -> None:
    from text_verification.workers import tasks as worker_tasks

    now = datetime(2026, 9, 1, 3, 0, tzinfo=UTC)
    repository = InMemoryJobRepository()
    verification_repository = InMemoryVerificationRepository()
    pipeline = RecordingPipeline(
        build_default_verification_pipeline(Settings(llm_api_key=""))
    )
    job_id = _seed_txt_job(
        repository,
        worker_storage,
        created_at=now - timedelta(hours=1),
        expires_at=now,
    )
    _configure_worker_dependencies(
        monkeypatch,
        repository,
        worker_storage,
        verification_repository=verification_repository,
        pipeline=pipeline,
    )
    scheduled: list[tuple[str, int]] = []
    monkeypatch.setattr(worker_tasks, "NOW_FACTORY", MutableClock(now))
    monkeypatch.setattr(
        worker_tasks,
        "RESCUE_SCHEDULER",
        lambda scheduled_job_id, countdown: scheduled.append(
            (scheduled_job_id, countdown)
        ),
    )

    outcome = worker_tasks._run_process_job_attempt(job_id, uuid4())
    worker_tasks._process_job(FakeBoundTask(), str(job_id))

    assert outcome.disposition.value == "retention_expired"
    assert pipeline.commands == []
    assert scheduled == []
    assert repository.get_job(job_id).status is JobStatus.QUEUED


def test_live_predecessor_retry_continues_after_retention_expiry(
    monkeypatch: pytest.MonkeyPatch,
    worker_storage: JobStorage,
) -> None:
    from text_verification.workers import tasks as worker_tasks

    now = datetime(2026, 9, 1, 3, 0, tzinfo=UTC)
    first_owner = uuid4()
    repository = InMemoryJobRepository()
    verification_repository = InMemoryVerificationRepository()
    pipeline = RecordingPipeline(
        build_default_verification_pipeline(Settings(llm_api_key=""))
    )
    job_id = _seed_txt_job(
        repository,
        worker_storage,
        created_at=now - timedelta(hours=1),
        expires_at=now - timedelta(seconds=1),
    )
    repository.force_lease(job_id, first_owner, now + timedelta(minutes=20))
    _configure_worker_dependencies(
        monkeypatch,
        repository,
        worker_storage,
        verification_repository=verification_repository,
        pipeline=pipeline,
    )
    monkeypatch.setattr(worker_tasks, "NOW_FACTORY", MutableClock(now))

    worker_tasks._process_job(
        FakeBoundTask(),
        str(job_id),
        previous_lease_owner_token=str(first_owner),
    )

    assert repository.get_job(job_id).status is JobStatus.COMPLETED
    assert len(pipeline.commands) == 1


def test_broker_confirmed_recovery_is_not_republished_during_worker_outage(
    monkeypatch: pytest.MonkeyPatch,
    worker_storage: JobStorage,
) -> None:
    from text_verification.workers import tasks as worker_tasks

    created_at = datetime(2026, 9, 1, 3, 0, tzinfo=UTC)
    repository = InMemoryJobRepository()
    job_id = _seed_txt_job(
        repository,
        worker_storage,
        created_at=created_at,
        expires_at=created_at + timedelta(hours=4),
    )
    _configure_worker_dependencies(monkeypatch, repository, worker_storage)
    clock = MutableClock(created_at + timedelta(minutes=2))
    published: list[str] = []
    monkeypatch.setattr(worker_tasks, "NOW_FACTORY", clock)
    monkeypatch.setattr(
        worker_tasks.process_job,
        "apply_async",
        lambda args, **kwargs: published.append(str(args[0])),
    )

    assert worker_tasks._rescue_expired_job_leases() == [str(job_id)]
    clock.current += timedelta(seconds=60)
    assert worker_tasks._rescue_expired_job_leases() == []
    clock.current += timedelta(hours=1)
    assert worker_tasks._rescue_expired_job_leases() == []

    assert published == [str(job_id)]


def test_publish_before_confirmation_crash_allows_one_later_republication(
    monkeypatch: pytest.MonkeyPatch,
    worker_storage: JobStorage,
) -> None:
    from text_verification.workers import tasks as worker_tasks

    created_at = datetime(2026, 9, 1, 3, 0, tzinfo=UTC)
    repository = InMemoryJobRepository()
    job_id = _seed_txt_job(
        repository,
        worker_storage,
        created_at=created_at,
        expires_at=created_at + timedelta(hours=4),
    )
    _configure_worker_dependencies(monkeypatch, repository, worker_storage)
    clock = MutableClock(created_at + timedelta(minutes=2))
    published: list[str] = []
    confirmation_attempts = 0
    real_mark_published = worker_tasks._mark_recovery_published

    def mark_published(*args, **kwargs) -> None:
        nonlocal confirmation_attempts
        confirmation_attempts += 1
        if confirmation_attempts == 1:
            raise RuntimeError("worker crashed before publication confirmation")
        real_mark_published(*args, **kwargs)

    monkeypatch.setattr(worker_tasks, "NOW_FACTORY", clock)
    monkeypatch.setattr(
        worker_tasks.process_job,
        "apply_async",
        lambda args, **kwargs: published.append(str(args[0])),
    )
    monkeypatch.setattr(worker_tasks, "_mark_recovery_published", mark_published)

    with pytest.raises(RuntimeError, match="before publication confirmation"):
        worker_tasks._rescue_expired_job_leases()

    clock.current += timedelta(seconds=119)
    assert worker_tasks._rescue_expired_job_leases() == []
    clock.current += timedelta(seconds=1)
    assert worker_tasks._rescue_expired_job_leases() == [str(job_id)]
    clock.current += timedelta(hours=1)
    assert worker_tasks._rescue_expired_job_leases() == []

    assert published == [str(job_id), str(job_id)]


def test_periodic_recovery_publish_failure_becomes_due_on_later_tick(
    monkeypatch: pytest.MonkeyPatch,
    worker_storage: JobStorage,
) -> None:
    from text_verification.workers import tasks as worker_tasks

    created_at = datetime(2026, 9, 1, 3, 0, tzinfo=UTC)
    repository = InMemoryJobRepository()
    job_id = _seed_txt_job(
        repository,
        worker_storage,
        created_at=created_at,
        expires_at=created_at + timedelta(hours=1),
    )
    _configure_worker_dependencies(monkeypatch, repository, worker_storage)
    clock = MutableClock(created_at + timedelta(minutes=2))
    attempts = 0

    def publish(args: tuple[str, ...], **kwargs: object) -> None:
        del args, kwargs
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("broker unavailable")

    monkeypatch.setattr(worker_tasks, "NOW_FACTORY", clock)
    monkeypatch.setattr(worker_tasks.process_job, "apply_async", publish)

    with pytest.raises(RuntimeError, match="broker unavailable"):
        worker_tasks._rescue_expired_job_leases()

    clock.current += timedelta(seconds=59)
    assert worker_tasks._rescue_expired_job_leases() == []
    clock.current += timedelta(seconds=1)
    assert worker_tasks._rescue_expired_job_leases() == [str(job_id)]
    assert attempts == 2
