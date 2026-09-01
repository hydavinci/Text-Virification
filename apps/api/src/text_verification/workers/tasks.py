from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from math import ceil
from typing import Any, NoReturn, cast
from uuid import UUID, uuid4

from celery import Task  # type: ignore[import-untyped]
from sqlalchemy.orm import Session, sessionmaker

from text_verification.application import (
    ArtifactPendingReconciliationService,
    VerificationError,
    VerificationPipeline,
    build_default_verification_pipeline,
)
from text_verification.compatibility.storage import CompatibilityStorage
from text_verification.config import get_settings
from text_verification.domain.jobs import (
    JobClaimDisposition,
    JobClaimResult,
    JobLeaseLostError,
    JobRead,
    JobStateConflictError,
    JobStatus,
    JobUnleasedError,
    TerminalJobStateError,
)
from text_verification.domain.ports import (
    VerificationProgressObserver,
    VerificationProgressStage,
)
from text_verification.domain.verification import VerificationResult
from text_verification.infrastructure.database import get_session_factory
from text_verification.infrastructure.repositories import JobRepository
from text_verification.infrastructure.storage import InvalidUpload, JobStorage
from text_verification.infrastructure.verification_repository import VerificationRepository
from text_verification.workers.celery_app import celery_app
from text_verification.workers.pipeline import (
    CHECKING_CHINESE_EVENT_MESSAGE,
    CHECKING_ENGLISH_EVENT_MESSAGE,
    CHECKING_FORMAT_EVENT_MESSAGE,
    CHECKING_SENSITIVE_EVENT_MESSAGE,
    COMPLETED_EVENT_MESSAGE,
    MISSING_UPLOAD_MESSAGE,
    PARSING_EVENT_MESSAGE,
    UPLOAD_VALIDATED_EVENT_MESSAGE,
    PipelineRunner,
)

logger = logging.getLogger(__name__)

FAILED_EVENT_MESSAGE = "处理失败"
PIPELINE_FAILURE_CODE = "pipeline_failed"
UNEXPECTED_FAILURE_MESSAGE = "Processing failed."

SessionFactoryProvider = Callable[[], sessionmaker[Session]]
StorageFactory = Callable[[], JobStorage]
CompatibilityStorageFactory = Callable[[], CompatibilityStorage]
RepositoryFactory = Callable[[Session], JobRepository]
VerificationRepositoryFactory = Callable[[Session], VerificationRepository]
PipelineFactory = Callable[[], VerificationPipeline]
RunnerFactory = Callable[[JobStorage, VerificationPipeline], PipelineRunner]
PROCESS_JOB_MAX_RETRIES = 2
PROCESS_JOB_RETRY_BACKOFF_CAP_SECONDS = 4
PROCESS_JOB_RESCUE_MAX_COUNTDOWN_SECONDS = 3600
PERIODIC_RESCUE_PUBLICATION_SECONDS = 120
PERIODIC_RESCUE_FAILURE_RETRY_SECONDS = 60
PERIODIC_RESCUE_LIMIT = 100

_STATUS_ORDER = (
    JobStatus.QUEUED,
    JobStatus.UPLOAD_VALIDATED,
    JobStatus.PARSING,
    JobStatus.CHECKING_FORMAT,
    JobStatus.CHECKING_SENSITIVE,
    JobStatus.CHECKING_CHINESE,
    JobStatus.CHECKING_ENGLISH,
)
_STATUS_EVENT_DETAILS = {
    JobStatus.UPLOAD_VALIDATED: (10, UPLOAD_VALIDATED_EVENT_MESSAGE),
    JobStatus.PARSING: (25, PARSING_EVENT_MESSAGE),
    JobStatus.CHECKING_FORMAT: (50, CHECKING_FORMAT_EVENT_MESSAGE),
    JobStatus.CHECKING_SENSITIVE: (65, CHECKING_SENSITIVE_EVENT_MESSAGE),
    JobStatus.CHECKING_CHINESE: (80, CHECKING_CHINESE_EVENT_MESSAGE),
    JobStatus.CHECKING_ENGLISH: (90, CHECKING_ENGLISH_EVENT_MESSAGE),
}
_STAGE_STATUSES = {
    VerificationProgressStage.PARSING: JobStatus.PARSING,
    VerificationProgressStage.CHECKING_FORMAT: JobStatus.CHECKING_FORMAT,
    VerificationProgressStage.CHECKING_SENSITIVE: JobStatus.CHECKING_SENSITIVE,
    VerificationProgressStage.CHECKING_CHINESE: JobStatus.CHECKING_CHINESE,
    VerificationProgressStage.CHECKING_ENGLISH: JobStatus.CHECKING_ENGLISH,
}


class ProcessAttemptDisposition(StrEnum):
    PROCESSED = "processed"
    MISSING = "missing"
    TERMINAL = "terminal"
    DUPLICATE = "duplicate"
    LEASE_LOST = "lease_lost"
    UNLEASED = "unleased"
    RETENTION_EXPIRED = "retention_expired"


@dataclass(frozen=True)
class ProcessAttemptOutcome:
    disposition: ProcessAttemptDisposition
    retry_at: datetime | None = None


def _get_job_storage() -> JobStorage:
    settings = get_settings()
    return JobStorage(settings.storage_root, settings.max_upload_bytes)


def _get_compatibility_storage() -> CompatibilityStorage:
    settings = get_settings()
    return CompatibilityStorage(settings.storage_root, settings.max_upload_bytes)


def _get_verification_pipeline() -> VerificationPipeline:
    return build_default_verification_pipeline(get_settings())


def _utc_now() -> datetime:
    return datetime.now(UTC)


SESSION_FACTORY_PROVIDER: SessionFactoryProvider = get_session_factory
STORAGE_FACTORY: StorageFactory = _get_job_storage
COMPATIBILITY_STORAGE_FACTORY: CompatibilityStorageFactory = _get_compatibility_storage
REPOSITORY_FACTORY: RepositoryFactory = JobRepository
VERIFICATION_REPOSITORY_FACTORY: VerificationRepositoryFactory = VerificationRepository
PIPELINE_FACTORY: PipelineFactory = _get_verification_pipeline
RUNNER_FACTORY: RunnerFactory = PipelineRunner
NOW_FACTORY: Callable[[], datetime] = _utc_now


class _LeaseProgressObserver(VerificationProgressObserver):
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        job_id: UUID,
        owner_token: UUID,
        current_status: JobStatus,
        lease_seconds: int,
    ) -> None:
        self._session_factory = session_factory
        self._job_id = job_id
        self._owner_token = owner_token
        self._lease_seconds = lease_seconds
        self.current_status = current_status

    def ensure_upload_validated(self) -> None:
        self._advance(JobStatus.UPLOAD_VALIDATED)

    def __call__(self, stage: VerificationProgressStage) -> None:
        self._advance(_STAGE_STATUSES[stage])

    def _advance(self, target_status: JobStatus) -> None:
        current_index = _STATUS_ORDER.index(self.current_status)
        target_index = _STATUS_ORDER.index(target_status)
        if target_index <= current_index:
            return
        if target_index != current_index + 1:
            raise JobStateConflictError(
                job_id=self._job_id,
                expected_status=_STATUS_ORDER[target_index - 1],
                current_status=self.current_status,
            )

        progress, message = _STATUS_EVENT_DETAILS[target_status]
        now = NOW_FACTORY()
        job = _transition_claimed(
            self._session_factory,
            self._job_id,
            owner_token=self._owner_token,
            expected_status=self.current_status,
            status=target_status,
            progress=progress,
            message=message,
            now=now,
            lease_expires_at=now + timedelta(seconds=self._lease_seconds),
        )
        self.current_status = job.status


def _process_job(
    task: Task,
    job_id: str,
    previous_lease_owner_token: str | None = None,
) -> None:
    parsed_job_id = UUID(job_id)
    previous_owner_token = (
        UUID(previous_lease_owner_token)
        if previous_lease_owner_token is not None
        else None
    )
    owner_token = uuid4()

    try:
        outcome = _run_process_job_attempt(
            parsed_job_id,
            owner_token,
            previous_owner_token=previous_owner_token,
        )
    except Exception as error:
        if task.request.retries < PROCESS_JOB_MAX_RETRIES:
            raise task.retry(
                exc=error,
                countdown=_retry_countdown(task.request.retries),
                kwargs={"previous_lease_owner_token": str(owner_token)},
            ) from error
        _persist_exhausted_failure(parsed_job_id, owner_token, error)
        _log_original_failure(parsed_job_id, error)
        _reraise(error)

    if outcome.disposition is ProcessAttemptDisposition.DUPLICATE:
        try:
            _schedule_lease_rescue(parsed_job_id, outcome.retry_at)
        except Exception as error:
            _log_rescue_publish_failure(parsed_job_id, error)
        else:
            logger.info(
                "process_job_duplicate_delivery",
                extra={"job_id": str(parsed_job_id)},
            )
    elif outcome.disposition is ProcessAttemptDisposition.LEASE_LOST:
        try:
            _schedule_lease_rescue(parsed_job_id, outcome.retry_at)
        except Exception as error:
            _log_rescue_publish_failure(parsed_job_id, error)
        else:
            logger.info(
                "process_job_lease_lost",
                extra={"job_id": str(parsed_job_id)},
            )
    elif outcome.disposition is ProcessAttemptDisposition.UNLEASED:
        logger.info(
            "process_job_unleased",
            extra={"job_id": str(parsed_job_id)},
        )


def _run_process_job_attempt(
    job_id: UUID,
    owner_token: UUID,
    *,
    previous_owner_token: UUID | None = None,
) -> ProcessAttemptOutcome:
    session_factory = SESSION_FACTORY_PROVIDER()
    lease_seconds = get_settings().job_lease_seconds
    claim = _acquire_claim(
        session_factory,
        job_id,
        owner_token=owner_token,
        previous_owner_token=previous_owner_token,
        lease_seconds=lease_seconds,
    )
    if claim.disposition is JobClaimDisposition.MISSING:
        return ProcessAttemptOutcome(ProcessAttemptDisposition.MISSING)
    if claim.disposition is JobClaimDisposition.TERMINAL:
        return ProcessAttemptOutcome(ProcessAttemptDisposition.TERMINAL)
    if claim.disposition is JobClaimDisposition.RETENTION_EXPIRED:
        return ProcessAttemptOutcome(ProcessAttemptDisposition.RETENTION_EXPIRED)
    if claim.disposition is JobClaimDisposition.LEASED:
        return ProcessAttemptOutcome(
            ProcessAttemptDisposition.DUPLICATE,
            claim.lease_expires_at,
        )
    job = claim.job
    if job is None:
        raise AssertionError("acquired claim must include the job")

    observer = _LeaseProgressObserver(
        session_factory=session_factory,
        job_id=job_id,
        owner_token=owner_token,
        current_status=job.status,
        lease_seconds=lease_seconds,
    )
    try:
        try:
            existing_result = _get_claimed_result(
                session_factory,
                job_id,
                owner_token=owner_token,
            )
            if existing_result is not None:
                if observer.current_status is not JobStatus.CHECKING_ENGLISH:
                    raise JobStateConflictError(
                        job_id=job_id,
                        expected_status=JobStatus.CHECKING_ENGLISH,
                        current_status=observer.current_status,
                    )
                _complete_claimed_job(
                    session_factory,
                    job_id,
                    owner_token=owner_token,
                    expected_status=observer.current_status,
                )
                return ProcessAttemptOutcome(ProcessAttemptDisposition.PROCESSED)

            observer.ensure_upload_validated()
            runner = RUNNER_FACTORY(STORAGE_FACTORY(), PIPELINE_FACTORY())
            result = runner.run(job, observer)
            _save_claimed_result(
                session_factory,
                job_id,
                result,
                owner_token=owner_token,
                expected_status=observer.current_status,
            )
            _complete_claimed_job(
                session_factory,
                job_id,
                owner_token=owner_token,
                expected_status=observer.current_status,
            )
            return ProcessAttemptOutcome(ProcessAttemptDisposition.PROCESSED)
        except InvalidUpload as error:
            return _persist_expected_failure(
                session_factory,
                job_id,
                owner_token=owner_token,
                expected_status=observer.current_status,
                error=error,
                error_message=MISSING_UPLOAD_MESSAGE,
            )
        except VerificationError as error:
            if error.retryable:
                raise
            return _persist_expected_failure(
                session_factory,
                job_id,
                owner_token=owner_token,
                expected_status=observer.current_status,
                error=error,
                error_message=error.message,
            )
    except JobLeaseLostError as error:
        return ProcessAttemptOutcome(
            ProcessAttemptDisposition.LEASE_LOST,
            error.lease_expires_at,
        )
    except JobUnleasedError:
        return ProcessAttemptOutcome(ProcessAttemptDisposition.UNLEASED)
    except TerminalJobStateError:
        return ProcessAttemptOutcome(ProcessAttemptDisposition.TERMINAL)


process_job = cast(
    Any,
    celery_app.task(
        bind=True,
        name="text_verification.process_job",
        max_retries=PROCESS_JOB_MAX_RETRIES,
        acks_late=True,
    )(_process_job),
)


def _default_rescue_scheduler(job_id: str, countdown: int) -> None:
    process_job.apply_async(args=(job_id,), countdown=countdown)


RESCUE_SCHEDULER: Callable[[str, int], None] = _default_rescue_scheduler


def _schedule_lease_rescue(
    job_id: UUID,
    retry_at: datetime | None,
) -> None:
    if retry_at is None:
        raise RuntimeError(f"Job {job_id} lease rescue is missing an expiry.")
    RESCUE_SCHEDULER(
        str(job_id),
        _rescue_countdown(retry_at, now=NOW_FACTORY()),
    )


def _rescue_countdown(
    retry_at: datetime,
    *,
    now: datetime,
) -> int:
    seconds = max(0, ceil((retry_at - now).total_seconds()))
    return min(seconds, PROCESS_JOB_RESCUE_MAX_COUNTDOWN_SECONDS)


def _rescue_expired_job_leases() -> list[str]:
    now = NOW_FACTORY()
    session_factory = SESSION_FACTORY_PROVIDER()
    session = session_factory()
    repository = REPOSITORY_FACTORY(session)
    try:
        claims = repository.claim_due_recoveries(
            now=now,
            publication_due_at=now
            + timedelta(seconds=PERIODIC_RESCUE_PUBLICATION_SECONDS),
            limit=PERIODIC_RESCUE_LIMIT,
        )
        repository.commit()
    except Exception:
        repository.rollback()
        raise
    finally:
        session.close()

    dispatched: list[str] = []
    for claim in claims:
        if claim.job is None:
            raise AssertionError("recoverable claim must include a job")
        job_id = str(claim.job.job_id)
        try:
            process_job.apply_async(args=(job_id,))
        except Exception as error:
            _mark_recovery_publish_failed(
                session_factory,
                claim.job.job_id,
                attempt=claim.attempt,
                now=now,
                retry_due_at=now
                + timedelta(seconds=PERIODIC_RESCUE_FAILURE_RETRY_SECONDS),
            )
            _log_rescue_publish_failure(claim.job.job_id, error)
            raise
        _mark_recovery_published(
            session_factory,
            claim.job.job_id,
            attempt=claim.attempt,
            published_at=now,
        )
        dispatched.append(job_id)
    return dispatched


rescue_expired_job_leases = cast(
    Any,
    celery_app.task(name="text_verification.rescue_expired_job_leases")(
        _rescue_expired_job_leases
    ),
)


def _cleanup_expired_jobs() -> list[str]:
    now = NOW_FACTORY()
    orphan_cutoff = now - timedelta(hours=get_settings().job_retention_hours)
    session_factory = SESSION_FACTORY_PROVIDER()
    session = session_factory()
    repository = REPOSITORY_FACTORY(session)

    try:
        expired_job_ids = repository.expire_jobs_before(now)
        persisted_job_ids = repository.list_job_ids()
        repository.commit()
    except Exception:
        repository.rollback()
        raise
    finally:
        session.close()

    storage = STORAGE_FACTORY()
    deleted_job_ids: list[str] = []
    for expired_job_id in expired_job_ids:
        try:
            artifact_storage_keys = _artifact_storage_keys(
                session_factory,
                expired_job_id,
            )
        except Exception as error:
            logger.warning(
                "cleanup_expired_job_metadata_failed",
                extra={
                    "job_id": str(expired_job_id),
                    "error_type": type(error).__name__,
                },
            )
            continue
        job_directory = storage.job_directory(expired_job_id)
        had_directory = job_directory.exists() or job_directory.is_symlink()
        deleted_artifact = False
        try:
            for storage_key in artifact_storage_keys:
                deleted_artifact = (
                    storage.delete_artifact(expired_job_id, storage_key)
                    or deleted_artifact
                )
            storage.delete_job(expired_job_id)
        except Exception as error:
            logger.warning(
                "cleanup_expired_job_delete_failed",
                extra={
                    "job_id": str(expired_job_id),
                    "error_type": type(error).__name__,
                },
            )
            continue
        try:
            _delete_results_for_job(session_factory, expired_job_id)
        except Exception as error:
            logger.warning(
                "cleanup_expired_job_result_delete_failed",
                extra={
                    "job_id": str(expired_job_id),
                    "error_type": type(error).__name__,
                },
            )
            continue
        if had_directory or deleted_artifact:
            deleted_job_ids.append(str(expired_job_id))
    deleted_job_ids.extend(
        str(orphan_id)
        for orphan_id in storage.delete_orphaned_directories(
            persisted_job_ids,
            orphan_cutoff,
        )
    )
    try:
        reconciliation = ArtifactPendingReconciliationService(
            storage,
            _artifact_repository_context_factory(session_factory),
        ).reconcile_before(orphan_cutoff)
        for artifact_id in reconciliation.deferred_artifact_ids:
            logger.warning(
                "cleanup_pending_artifact_reconciliation_deferred",
                extra={"export_artifact_id": str(artifact_id)},
            )
    except Exception as error:
        logger.warning(
            "cleanup_pending_artifact_reconciliation_failed",
            extra={"error_type": type(error).__name__},
        )
    try:
        referenced_artifact_keys = _all_artifact_storage_keys(session_factory)
    except Exception as error:
        logger.warning(
            "cleanup_artifact_metadata_failed",
            extra={"error_type": type(error).__name__},
        )
    else:
        try:
            storage.delete_orphaned_artifacts(
                set(referenced_artifact_keys),
                orphan_cutoff,
            )
        except Exception as error:
            logger.warning(
                "cleanup_orphaned_artifacts_failed",
                extra={"error_type": type(error).__name__},
            )
    try:
        COMPATIBILITY_STORAGE_FACTORY().delete_stale_directories(orphan_cutoff)
    except Exception as error:
        logger.warning(
            "compatibility_cleanup_failed",
            extra={"error_type": type(error).__name__},
        )
    return deleted_job_ids


cleanup_expired_jobs = cast(
    Any,
    celery_app.task(name="text_verification.cleanup_expired_jobs")(_cleanup_expired_jobs),
)


def dispatch_process_job(job_id: str) -> None:
    process_job.delay(job_id)


def _acquire_claim(
    session_factory: sessionmaker[Session],
    job_id: UUID,
    *,
    owner_token: UUID,
    previous_owner_token: UUID | None = None,
    lease_seconds: int,
) -> JobClaimResult:
    session = session_factory()
    repository = REPOSITORY_FACTORY(session)
    now = NOW_FACTORY()
    try:
        claim = repository.acquire_lease(
            job_id,
            owner_token=owner_token,
            previous_owner_token=previous_owner_token,
            now=now,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
        )
        repository.commit()
        return claim
    except Exception:
        repository.rollback()
        raise
    finally:
        session.close()


def _transition_claimed(
    session_factory: sessionmaker[Session],
    job_id: UUID,
    *,
    owner_token: UUID,
    expected_status: JobStatus,
    status: JobStatus,
    progress: int,
    message: str,
    now: datetime,
    lease_expires_at: datetime,
) -> JobRead:
    session = session_factory()
    repository = REPOSITORY_FACTORY(session)
    try:
        job = repository.transition_claimed(
            job_id,
            owner_token=owner_token,
            expected_status=expected_status,
            status=status,
            progress=progress,
            message=message,
            now=now,
            lease_expires_at=lease_expires_at,
        )
        repository.commit()
        return job
    except Exception:
        repository.rollback()
        raise
    finally:
        session.close()


def _mark_recovery_published(
    session_factory: sessionmaker[Session],
    job_id: UUID,
    *,
    attempt: int,
    published_at: datetime,
) -> None:
    session = session_factory()
    repository = REPOSITORY_FACTORY(session)
    try:
        repository.mark_recovery_published(
            job_id,
            attempt=attempt,
            published_at=published_at,
        )
        repository.commit()
    except Exception:
        repository.rollback()
        raise
    finally:
        session.close()


def _mark_recovery_publish_failed(
    session_factory: sessionmaker[Session],
    job_id: UUID,
    *,
    attempt: int,
    now: datetime,
    retry_due_at: datetime,
) -> None:
    session = session_factory()
    repository = REPOSITORY_FACTORY(session)
    try:
        repository.mark_recovery_publish_failed(
            job_id,
            attempt=attempt,
            now=now,
            retry_due_at=retry_due_at,
        )
        repository.commit()
    except Exception:
        repository.rollback()
        raise
    finally:
        session.close()


def _artifact_storage_keys(
    session_factory: sessionmaker[Session],
    job_id: UUID,
) -> tuple[str, ...]:
    session = session_factory()
    repository = VERIFICATION_REPOSITORY_FACTORY(session)
    try:
        return repository.list_artifact_storage_keys(job_id)
    finally:
        repository.rollback()
        session.close()


def _artifact_repository_context_factory(
    session_factory: sessionmaker[Session],
) -> Callable[[], AbstractContextManager[VerificationRepository]]:
    @contextmanager
    def repository_context() -> Iterator[VerificationRepository]:
        session = session_factory()
        try:
            yield VERIFICATION_REPOSITORY_FACTORY(session)
        finally:
            session.close()

    return repository_context


def _all_artifact_storage_keys(
    session_factory: sessionmaker[Session],
) -> tuple[str, ...]:
    session = session_factory()
    repository = VERIFICATION_REPOSITORY_FACTORY(session)
    try:
        return repository.list_all_artifact_storage_keys()
    finally:
        repository.rollback()
        session.close()


def _delete_results_for_job(
    session_factory: sessionmaker[Session],
    job_id: UUID,
) -> None:
    session = session_factory()
    repository = VERIFICATION_REPOSITORY_FACTORY(session)
    try:
        repository.delete_results_for_jobs([job_id])
        repository.commit()
    except Exception:
        repository.rollback()
        raise
    finally:
        session.close()


def _get_claimed_result(
    session_factory: sessionmaker[Session],
    job_id: UUID,
    *,
    owner_token: UUID,
) -> VerificationResult | None:
    session = session_factory()
    repository = VERIFICATION_REPOSITORY_FACTORY(session)
    try:
        return repository.get_result_for_claimed_job(
            job_id,
            owner_token=owner_token,
            now=NOW_FACTORY(),
        )
    finally:
        repository.rollback()
        session.close()


def _save_claimed_result(
    session_factory: sessionmaker[Session],
    job_id: UUID,
    result: VerificationResult,
    *,
    owner_token: UUID,
    expected_status: JobStatus,
) -> None:
    session = session_factory()
    repository = VERIFICATION_REPOSITORY_FACTORY(session)
    try:
        repository.save_claimed_result(
            job_id,
            result,
            owner_token=owner_token,
            expected_status=expected_status,
            now=NOW_FACTORY(),
        )
        repository.commit()
    except Exception:
        repository.rollback()
        raise
    finally:
        session.close()


def _complete_claimed_job(
    session_factory: sessionmaker[Session],
    job_id: UUID,
    *,
    owner_token: UUID,
    expected_status: JobStatus,
) -> None:
    session = session_factory()
    repository = REPOSITORY_FACTORY(session)
    try:
        repository.complete_claimed_job(
            job_id,
            owner_token=owner_token,
            expected_status=expected_status,
            progress=100,
            message=COMPLETED_EVENT_MESSAGE,
            now=NOW_FACTORY(),
        )
        repository.commit()
    except Exception:
        repository.rollback()
        raise
    finally:
        session.close()


def _persist_expected_failure(
    session_factory: sessionmaker[Session],
    job_id: UUID,
    *,
    owner_token: UUID,
    expected_status: JobStatus,
    error: Exception,
    error_message: str,
) -> ProcessAttemptOutcome:
    try:
        failure_applied = _fail_claimed_job(
            session_factory,
            job_id,
            owner_token=owner_token,
            expected_status=expected_status,
            error_message=error_message,
        )
        if not failure_applied:
            _complete_claimed_job(
                session_factory,
                job_id,
                owner_token=owner_token,
                expected_status=expected_status,
            )
        return ProcessAttemptOutcome(ProcessAttemptDisposition.PROCESSED)
    except (JobLeaseLostError, TerminalJobStateError):
        raise
    except Exception as persist_error:
        _log_failure_persist_error(job_id, error, persist_error)
        raise


def _fail_claimed_job(
    session_factory: sessionmaker[Session],
    job_id: UUID,
    *,
    owner_token: UUID,
    expected_status: JobStatus,
    error_message: str,
) -> bool:
    session = session_factory()
    repository = REPOSITORY_FACTORY(session)
    try:
        job = repository.get_job(job_id)
        progress = 0 if job is None else job.progress
        applied = repository.fail_claimed_job(
            job_id,
            owner_token=owner_token,
            expected_status=expected_status,
            progress=progress,
            message=FAILED_EVENT_MESSAGE,
            error_code=PIPELINE_FAILURE_CODE,
            error_message=error_message,
            now=NOW_FACTORY(),
        )
        repository.commit()
        return applied
    except Exception:
        repository.rollback()
        raise
    finally:
        session.close()


def _persist_exhausted_failure(
    job_id: UUID,
    owner_token: UUID,
    error: Exception,
) -> None:
    try:
        session_factory = SESSION_FACTORY_PROVIDER()
        failure_owner_token = uuid4()
        claim = _acquire_claim(
            session_factory,
            job_id,
            owner_token=failure_owner_token,
            previous_owner_token=owner_token,
            lease_seconds=get_settings().job_lease_seconds,
        )
        if claim.disposition is not JobClaimDisposition.ACQUIRED or claim.job is None:
            return
        failure_applied = _fail_claimed_job(
            session_factory,
            job_id,
            owner_token=failure_owner_token,
            expected_status=claim.job.status,
            error_message=UNEXPECTED_FAILURE_MESSAGE,
        )
        if not failure_applied and claim.job.status is JobStatus.CHECKING_ENGLISH:
            _complete_claimed_job(
                session_factory,
                job_id,
                owner_token=failure_owner_token,
                expected_status=claim.job.status,
            )
    except (JobLeaseLostError, JobStateConflictError, TerminalJobStateError):
        return
    except Exception as persist_error:
        _log_failure_persist_error(job_id, error, persist_error)


def _log_failure_persist_error(
    job_id: UUID,
    original_error: Exception,
    persist_error: Exception,
) -> None:
    logger.error(
        "process_job_failure_persist_failed",
        extra={
            "job_id": str(job_id),
            "original_error_type": type(original_error).__name__,
            "persistence_error_type": type(persist_error).__name__,
        },
    )


def _log_original_failure(job_id: UUID, error: Exception) -> None:
    logger.error(
        "process_job_failed",
        extra={
            "job_id": str(job_id),
            "error_type": type(error).__name__,
        },
    )


def _log_rescue_publish_failure(job_id: UUID, error: Exception) -> None:
    logger.error(
        "process_job_rescue_publish_failed",
        extra={
            "job_id": str(job_id),
            "error_type": type(error).__name__,
        },
    )


def _retry_countdown(retries: int) -> int:
    return int(min(2**retries, PROCESS_JOB_RETRY_BACKOFF_CAP_SECONDS))


def _reraise(error: Exception) -> NoReturn:
    raise error.with_traceback(error.__traceback__)
