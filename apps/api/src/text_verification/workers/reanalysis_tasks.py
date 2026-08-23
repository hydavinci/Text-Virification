from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, NoReturn, cast
from uuid import UUID

from celery import Task  # type: ignore[import-untyped]
from sqlalchemy.orm import Session, sessionmaker

from text_verification.checkers.dictionary_loader import DictionaryConfigurationError
from text_verification.checkers.models import CHECK_CATEGORY_ORDER, CheckOptions, CheckScenario
from text_verification.checkers.rule_loader import RuleConfigurationError
from text_verification.domain.documents import DocumentModel
from text_verification.domain.jobs import JobRead, JobStatus
from text_verification.domain.revisions import DocumentVersionStatus, EditDraftRead
from text_verification.infrastructure.analysis_repositories import AnalysisRepository
from text_verification.infrastructure.database import get_session_factory
from text_verification.infrastructure.repositories import JobRepository
from text_verification.infrastructure.revision_repository import (
    DraftConsumedError,
    DraftNotFoundError,
    InvalidBaseVersionError,
    InvalidReanalysisVersionError,
    RevisionRepository,
    StaleDocumentVersionError,
    StaleDraftRevisionError,
    VersionNotFoundError,
)
from text_verification.workers import tasks as worker_tasks
from text_verification.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

PROCESS_DOCUMENT_VERSION_MAX_RETRIES = 2
PROCESS_DOCUMENT_VERSION_RETRY_BACKOFF_CAP_SECONDS = 4
VERSION_FAILURE_PERSIST_MAX_ATTEMPTS = 3
REANALYSIS_FAILURE_CODE = "reanalysis_failed"
REANALYSIS_FAILURE_MESSAGE = "重新分析失败，请稍后重试。"

SessionFactoryProvider = Callable[[], sessionmaker[Session]]
RunnerFactory = Callable[[Session, JobRepository], Any]


class ExpiredReanalysisJobError(RuntimeError):
    pass


class VersionFailurePersistenceError(RuntimeError):
    def __init__(self, version_id: UUID) -> None:
        self.version_id = version_id
        super().__init__(f"Failed to persist terminal state for document version {version_id}.")


def _build_runner(session: Session, repository: JobRepository) -> Any:
    return worker_tasks.RUNNER_FACTORY(session, repository, worker_tasks.STORAGE_FACTORY())


SESSION_FACTORY_PROVIDER: SessionFactoryProvider = get_session_factory
RUNNER_FACTORY: RunnerFactory = _build_runner


def _process_document_version(task: Task, version_id: str) -> None:
    parsed_version_id = UUID(version_id)
    try:
        _run_process_document_version_attempt(parsed_version_id)
    except VersionFailurePersistenceError:
        raise
    except Exception as error:
        if task.request.retries < PROCESS_DOCUMENT_VERSION_MAX_RETRIES:
            raise task.retry(
                exc=error,
                countdown=_retry_countdown(task.request.retries),
            ) from error
        _persist_exhausted_failure(parsed_version_id, error)
        _log_original_failure(parsed_version_id, error)
        _reraise(error)


def _run_process_document_version_attempt(version_id: UUID) -> None:
    session: Session | None = None
    try:
        session_factory = SESSION_FACTORY_PROVIDER()
        session = session_factory()
        revisions = RevisionRepository(session)
        version, draft_id, expected_draft_revision = revisions.get_reanalysis_request(version_id)
        if version.status in {DocumentVersionStatus.SUCCEEDED, DocumentVersionStatus.FAILED}:
            return
        if version.parent_version_id is None:
            raise InvalidReanalysisVersionError(version_id)

        repository = JobRepository(session)
        job = repository.get_job(version.job_id)
        if job is None:
            return
        if job.status == JobStatus.EXPIRED or job.expires_at <= datetime.now(UTC):
            raise ExpiredReanalysisJobError(version.job_id)

        draft = revisions.get_reanalysis_draft(
            version.job_id,
            draft_id,
            expected_revision=expected_draft_revision,
        )
        base_document = AnalysisRepository(session).get_document(
            version.job_id,
            version.parent_version_id,
        )
        if base_document is None:
            raise InvalidReanalysisVersionError(version_id)

        runner = RUNNER_FACTORY(session, repository)
        runner.analyze_document(
            version.version_id,
            _build_reanalysis_document(
                version.revision_number,
                base_document,
                draft,
            ),
            _check_options_for(job),
        )
        session.commit()
    except VersionNotFoundError:
        if session is not None:
            session.rollback()
        return
    except _EXPECTED_REANALYSIS_FAILURES as error:
        if session is not None:
            session.rollback()
        _persist_expected_failure(version_id, error)
    except Exception:
        if session is not None:
            session.rollback()
        raise
    finally:
        if session is not None:
            session.close()


process_document_version = cast(
    Any,
    celery_app.task(
        bind=True,
        name="text_verification.process_document_version",
        max_retries=PROCESS_DOCUMENT_VERSION_MAX_RETRIES,
        acks_late=True,
        reject_on_worker_lost=True,
    )(_process_document_version),
)


def dispatch_process_document_version(version_id: str) -> None:
    process_document_version.delay(version_id)


_EXPECTED_REANALYSIS_FAILURES = (
    DraftConsumedError,
    DraftNotFoundError,
    InvalidBaseVersionError,
    InvalidReanalysisVersionError,
    RuleConfigurationError,
    DictionaryConfigurationError,
    ExpiredReanalysisJobError,
    StaleDocumentVersionError,
    StaleDraftRevisionError,
)


def _persist_expected_failure(version_id: UUID, error: Exception) -> None:
    code, message = _expected_failure_details(error)
    _persist_failure(
        version_id,
        code=code,
        message=message,
        original_error=error,
    )


def _persist_exhausted_failure(version_id: UUID, error: Exception) -> None:
    _persist_failure(
        version_id,
        code=REANALYSIS_FAILURE_CODE,
        message=REANALYSIS_FAILURE_MESSAGE,
        original_error=error,
    )


def _persist_failure(
    version_id: UUID,
    *,
    code: str,
    message: str,
    original_error: Exception | None = None,
) -> None:
    last_error: Exception | None = None
    for attempt in range(1, VERSION_FAILURE_PERSIST_MAX_ATTEMPTS + 1):
        session: Session | None = None
        try:
            session_factory = SESSION_FACTORY_PROVIDER()
            session = session_factory()
            revisions = RevisionRepository(session)
            version = revisions.get_version(version_id)
            if version is None or version.status in {
                DocumentVersionStatus.SUCCEEDED,
                DocumentVersionStatus.FAILED,
            }:
                return
            revisions.fail_version(version_id, code=code, message=message)
            session.commit()
            return
        except Exception as persist_error:
            last_error = persist_error
            if session is not None:
                session.rollback()
            logger.error(
                "process_document_version_failure_persist_failed",
                extra={
                    "version_id": str(version_id),
                    "attempt": attempt,
                    "original_error_type": (
                        None if original_error is None else type(original_error).__name__
                    ),
                    "persistence_error_type": type(persist_error).__name__,
                },
            )
        finally:
            if session is not None:
                session.close()

    raise VersionFailurePersistenceError(version_id) from last_error


def _expected_failure_details(error: Exception) -> tuple[str, str]:
    if isinstance(error, ExpiredReanalysisJobError):
        return "job_expired", "作业已过期，请重新上传文件。"
    if isinstance(error, DraftNotFoundError):
        return "draft_not_found", "草稿不存在。"
    if isinstance(error, DraftConsumedError):
        return "draft_consumed", "草稿已被消费，请刷新后重试。"
    if isinstance(error, StaleDraftRevisionError):
        return "stale_draft_revision", "草稿已更新，请刷新后重试。"
    if isinstance(error, StaleDocumentVersionError):
        return "stale_document_version", "已有更新版本完成，当前重新分析结果已过期。"
    if isinstance(error, RuleConfigurationError | DictionaryConfigurationError):
        return error.code, error.public_message
    if isinstance(error, InvalidBaseVersionError):
        return "invalid_base_version", "只能基于成功版本创建草稿。"
    return "invalid_reanalysis_version", "重新分析请求无效，请刷新后重试。"


def _build_reanalysis_document(
    version_number: int,
    base_document: DocumentModel,
    draft: EditDraftRead,
) -> DocumentModel:
    draft_text_by_block_id = {block.block_id: block.text for block in draft.blocks}
    base_block_ids = [block.block_id for block in base_document.blocks]
    if set(base_block_ids) != set(draft_text_by_block_id):
        raise InvalidReanalysisVersionError(base_document.document_id)
    return base_document.model_copy(
        update={
            "version": version_number,
            "blocks": [
                block.model_copy(update={"text": draft_text_by_block_id[block.block_id]})
                for block in base_document.blocks
            ],
        },
        deep=True,
    )


def _check_options_for(job: JobRead) -> CheckOptions:
    scenario = getattr(job, "scenario", None) or CheckScenario.GENERAL
    enabled_categories = getattr(job, "enabled_categories", None)
    if enabled_categories is None:
        enabled_categories = CHECK_CATEGORY_ORDER
    return CheckOptions(scenario=scenario, enabled_categories=enabled_categories)


def _retry_countdown(retries: int) -> int:
    return int(min(2**retries, PROCESS_DOCUMENT_VERSION_RETRY_BACKOFF_CAP_SECONDS))


def _log_original_failure(version_id: UUID, error: Exception) -> None:
    logger.error(
        "process_document_version_failed",
        extra={
            "version_id": str(version_id),
            "error_type": type(error).__name__,
        },
    )


def _reraise(error: Exception) -> NoReturn:
    raise error.with_traceback(error.__traceback__)
