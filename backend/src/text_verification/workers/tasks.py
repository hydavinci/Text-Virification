from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, NoReturn, cast
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from text_verification.config import get_settings
from text_verification.domain.jobs import TERMINAL_STATUSES, JobStatus
from text_verification.infrastructure.database import get_session_factory
from text_verification.infrastructure.repositories import JobRepository
from text_verification.infrastructure.storage import InvalidUpload, JobStorage
from text_verification.workers.celery_app import celery_app
from text_verification.workers.pipeline import MISSING_UPLOAD_MESSAGE, PipelineRunner

logger = logging.getLogger(__name__)

FAILED_EVENT_MESSAGE = "处理失败"
PIPELINE_FAILURE_CODE = "pipeline_failed"
UNEXPECTED_FAILURE_MESSAGE = "Processing failed."

SessionFactoryProvider = Callable[[], sessionmaker[Session]]
StorageFactory = Callable[[], JobStorage]
RepositoryFactory = Callable[[Session], JobRepository]
RunnerFactory = Callable[[JobRepository, JobStorage], PipelineRunner]

def _get_job_storage() -> JobStorage:
    settings = get_settings()
    return JobStorage(settings.storage_root, settings.max_upload_bytes)


SESSION_FACTORY_PROVIDER: SessionFactoryProvider = get_session_factory
STORAGE_FACTORY: StorageFactory = _get_job_storage
REPOSITORY_FACTORY: RepositoryFactory = JobRepository
RUNNER_FACTORY: RunnerFactory = PipelineRunner


def _process_job(job_id: str) -> None:
    parsed_job_id = UUID(job_id)
    session_factory = SESSION_FACTORY_PROVIDER()
    session = session_factory()

    try:
        repository = REPOSITORY_FACTORY(session)
        job = repository.get_job(parsed_job_id)
        if job is None or job.status in TERMINAL_STATUSES:
            return

        try:
            storage = STORAGE_FACTORY()
            runner = RUNNER_FACTORY(repository, storage)
            runner.run(parsed_job_id)
        except InvalidUpload as error:
            _persist_expected_failure(repository, parsed_job_id, error)
        except Exception as error:
            _persist_unexpected_failure(repository, parsed_job_id, error)
    finally:
        session.close()


process_job = cast(Any, celery_app.task(name="text_verification.process_job")(_process_job))


def dispatch_process_job(job_id: str) -> None:
    process_job.delay(job_id)


def _persist_expected_failure(
    repository: JobRepository,
    job_id: UUID,
    error: InvalidUpload,
) -> None:
    try:
        _mark_failed_job(repository, job_id, MISSING_UPLOAD_MESSAGE)
    except Exception as persist_error:
        repository.rollback()
        _log_failure_persist_error(job_id, error, persist_error)
        _log_original_failure(job_id, error)
        _reraise(error)


def _persist_unexpected_failure(
    repository: JobRepository,
    job_id: UUID,
    error: Exception,
) -> NoReturn:
    try:
        _mark_failed_job(repository, job_id, UNEXPECTED_FAILURE_MESSAGE)
    except Exception as persist_error:
        repository.rollback()
        _log_failure_persist_error(job_id, error, persist_error)
        _log_original_failure(job_id, error)
        _reraise(error)

    _log_original_failure(job_id, error)
    _reraise(error)


def _mark_failed_job(
    repository: JobRepository,
    job_id: UUID,
    error_message: str,
) -> None:
    job = repository.get_job(job_id)
    progress = 0 if job is None else job.progress
    repository.transition(
        job_id,
        JobStatus.FAILED,
        progress,
        FAILED_EVENT_MESSAGE,
        error_code=PIPELINE_FAILURE_CODE,
        error_message=error_message,
    )
    repository.commit()


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


def _reraise(error: Exception) -> NoReturn:
    raise error.with_traceback(error.__traceback__)
