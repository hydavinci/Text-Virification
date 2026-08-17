from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any, NoReturn, cast
from uuid import UUID

from celery import Task  # type: ignore[import-untyped]
from sqlalchemy.orm import Session, sessionmaker

from text_verification.checkers import CheckerRegistry, RuleLoader
from text_verification.checkers.dictionary_checker import DictionaryChecker
from text_verification.checkers.dictionary_loader import (
    DictionaryConfigurationError,
    DictionaryLoader,
)
from text_verification.checkers.models import CheckCategory
from text_verification.checkers.rule_loader import RuleConfigurationError
from text_verification.config import get_settings
from text_verification.domain.documents import ParseError
from text_verification.domain.jobs import (
    TERMINAL_STATUSES,
    JobStatus,
    TerminalJobStateError,
)
from text_verification.domain.ports import CheckContext
from text_verification.infrastructure.analysis_repositories import AnalysisRepository
from text_verification.infrastructure.database import get_session_factory
from text_verification.infrastructure.repositories import JobRepository
from text_verification.infrastructure.storage import InvalidUpload, JobStorage
from text_verification.parsers import DocxParser, ParserRegistry, PdfParser, TxtParser
from text_verification.workers.celery_app import celery_app
from text_verification.workers.pipeline import MISSING_UPLOAD_MESSAGE, PipelineRunner

logger = logging.getLogger(__name__)

FAILED_EVENT_MESSAGE = "处理失败"
PIPELINE_FAILURE_CODE = "pipeline_failed"
UNEXPECTED_FAILURE_MESSAGE = "处理失败，请稍后重新上传文件重试。"

SessionFactoryProvider = Callable[[], sessionmaker[Session]]
StorageFactory = Callable[[], JobStorage]
RepositoryFactory = Callable[[Session], JobRepository]
RunnerFactory = Callable[[Session, JobRepository, JobStorage], PipelineRunner]
PROCESS_JOB_MAX_RETRIES = 2
PROCESS_JOB_RETRY_BACKOFF_CAP_SECONDS = 4


def _get_job_storage() -> JobStorage:
    settings = get_settings()
    return JobStorage(settings.storage_root, settings.max_upload_bytes)


SESSION_FACTORY_PROVIDER: SessionFactoryProvider = get_session_factory
STORAGE_FACTORY: StorageFactory = _get_job_storage
REPOSITORY_FACTORY: RepositoryFactory = JobRepository
RUNNER_FACTORY: RunnerFactory


@lru_cache(maxsize=1)
def _build_parser_registry() -> ParserRegistry:
    return ParserRegistry((TxtParser(), PdfParser(), DocxParser()))


@lru_cache(maxsize=1)
def _build_checker_registry() -> CheckerRegistry:
    settings = get_settings()
    rule_set = RuleLoader(
        settings.rules_root / "common-rules.zh-cn.json",
        settings.rules_root / "scenarios.zh-cn.json",
    ).load()
    return CheckerRegistry.from_rule_set(
        rule_set,
        additional_checkers={
            CheckCategory.SECURITY: DictionaryChecker(),
        },
    )


@lru_cache(maxsize=1)
def _build_check_context() -> CheckContext:
    settings = get_settings()
    return CheckContext(
        (),
        (),
        shared_dictionaries=DictionaryLoader(settings.dictionaries_root).load(),
    )


def _build_pipeline_runner(
    session: Session,
    repository: JobRepository,
    storage: JobStorage,
) -> PipelineRunner:
    return PipelineRunner(
        repository,
        AnalysisRepository(session),
        storage,
        _build_parser_registry(),
        _build_checker_registry(),
        _build_check_context(),
    )


RUNNER_FACTORY = _build_pipeline_runner


def _process_job(task: Task, job_id: str) -> None:
    parsed_job_id = UUID(job_id)

    try:
        _run_process_job_attempt(parsed_job_id)
    except Exception as error:
        if task.request.retries < PROCESS_JOB_MAX_RETRIES:
            raise task.retry(
                exc=error,
                countdown=_retry_countdown(task.request.retries),
            ) from error
        _persist_exhausted_failure(parsed_job_id, error)
        _log_original_failure(parsed_job_id, error)
        _reraise(error)


def _run_process_job_attempt(job_id: UUID) -> None:
    session: Session | None = None
    repository: JobRepository | None = None
    try:
        session_factory = SESSION_FACTORY_PROVIDER()
        session = session_factory()
        repository = REPOSITORY_FACTORY(session)
        job = repository.get_job(job_id)
        if job is None or job.status in TERMINAL_STATUSES:
            return

        storage = STORAGE_FACTORY()
        runner = RUNNER_FACTORY(session, repository, storage)
        runner.run(job_id)
    except TerminalJobStateError:
        if repository is not None:
            repository.rollback()
    except InvalidUpload as error:
        if repository is None:
            raise
        _persist_expected_failure(repository, job_id, error)
    except ParseError as error:
        if repository is None:
            raise
        _persist_parse_failure(repository, job_id, error)
    except (RuleConfigurationError, DictionaryConfigurationError) as error:
        if repository is None:
            raise
        _persist_configuration_failure(repository, job_id, error)
    except Exception:
        if repository is not None:
            repository.rollback()
        raise
    finally:
        if session is not None:
            session.close()


process_job = cast(
    Any,
    celery_app.task(
        bind=True,
        name="text_verification.process_job",
        max_retries=PROCESS_JOB_MAX_RETRIES,
        acks_late=True,
    )(_process_job),
)


def _cleanup_expired_jobs() -> list[str]:
    now = datetime.now(UTC)
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
    for job_id in expired_job_ids:
        job_directory = storage.job_directory(job_id)
        had_directory = job_directory.exists() or job_directory.is_symlink()
        try:
            storage.delete_job(job_id)
        except Exception as error:
            logger.warning(
                "cleanup_expired_job_delete_failed",
                extra={
                    "job_id": str(job_id),
                    "error_type": type(error).__name__,
                },
            )
            continue
        if had_directory:
            deleted_job_ids.append(str(job_id))
    deleted_job_ids.extend(
        str(job_id)
        for job_id in storage.delete_orphaned_directories(persisted_job_ids, orphan_cutoff)
    )
    return deleted_job_ids


cleanup_expired_jobs = cast(
    Any,
    celery_app.task(name="text_verification.cleanup_expired_jobs")(_cleanup_expired_jobs),
)


def dispatch_process_job(job_id: str) -> None:
    process_job.delay(job_id)


def _persist_expected_failure(
    repository: JobRepository,
    job_id: UUID,
    error: InvalidUpload,
) -> None:
    try:
        _mark_failed_job(
            repository,
            job_id,
            PIPELINE_FAILURE_CODE,
            MISSING_UPLOAD_MESSAGE,
        )
    except TerminalJobStateError:
        repository.rollback()
        return
    except Exception as persist_error:
        repository.rollback()
        _log_failure_persist_error(job_id, error, persist_error)
        raise


def _persist_parse_failure(
    repository: JobRepository,
    job_id: UUID,
    error: ParseError,
) -> None:
    try:
        _mark_failed_job(repository, job_id, error.code, error.public_message)
    except TerminalJobStateError:
        repository.rollback()
        return
    except Exception as persist_error:
        repository.rollback()
        _log_failure_persist_error(job_id, error, persist_error)
        raise


def _persist_configuration_failure(
    repository: JobRepository,
    job_id: UUID,
    error: RuleConfigurationError | DictionaryConfigurationError,
) -> None:
    try:
        _mark_failed_job(repository, job_id, error.code, error.public_message)
    except TerminalJobStateError:
        repository.rollback()
        return
    except Exception as persist_error:
        repository.rollback()
        _log_failure_persist_error(job_id, error, persist_error)
        raise


def _persist_exhausted_failure(
    job_id: UUID,
    error: Exception,
) -> None:
    session: Session | None = None
    repository: JobRepository | None = None
    try:
        session_factory = SESSION_FACTORY_PROVIDER()
        session = session_factory()
        repository = REPOSITORY_FACTORY(session)
        job = repository.get_job(job_id)
        if job is None or job.status in TERMINAL_STATUSES:
            return
        _mark_failed_job(
            repository,
            job_id,
            PIPELINE_FAILURE_CODE,
            UNEXPECTED_FAILURE_MESSAGE,
        )
    except TerminalJobStateError:
        if repository is not None:
            repository.rollback()
    except Exception as persist_error:
        if repository is not None:
            repository.rollback()
        _log_failure_persist_error(job_id, error, persist_error)
    finally:
        if session is not None:
            session.close()


def _mark_failed_job(
    repository: JobRepository,
    job_id: UUID,
    error_code: str,
    error_message: str,
) -> None:
    job = repository.get_job(job_id)
    progress = 0 if job is None else job.progress
    repository.transition(
        job_id,
        JobStatus.FAILED,
        progress,
        FAILED_EVENT_MESSAGE,
        error_code=error_code,
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


def _retry_countdown(retries: int) -> int:
    return int(min(2**retries, PROCESS_JOB_RETRY_BACKOFF_CAP_SECONDS))


def _reraise(error: Exception) -> NoReturn:
    raise error.with_traceback(error.__traceback__)
