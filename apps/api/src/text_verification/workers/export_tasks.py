from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from hashlib import blake2b, sha256
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from celery import Task  # type: ignore[import-untyped]
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from text_verification.config import get_settings
from text_verification.domain.documents import FileType
from text_verification.domain.exports import (
    ExportRead,
    ExportSnapshot,
    ExportStatus,
    ExportType,
    TerminalExportStateError,
)
from text_verification.exporters import (
    DocxApplicabilityEvaluator,
    DocxExporter,
    ExportError,
    ExportWarning,
    ReplacementPlan,
    ReplacementPlanner,
    ReportCategoryFailure,
    ReportExporter,
    ReportModel,
    ReportSummary,
    TxtExporter,
)
from text_verification.infrastructure.database import get_session_factory
from text_verification.infrastructure.export_repository import ExportRepository
from text_verification.infrastructure.storage import JobStorage
from text_verification.workers.celery_app import (
    TASK_HARD_TIME_LIMIT_SECONDS,
    celery_app,
)

logger = logging.getLogger(__name__)

PROCESS_EXPORT_MAX_RETRIES = 2
PROCESS_EXPORT_RETRY_BACKOFF_CAP_SECONDS = 4
QUEUED_EXPORT_RECOVERY_AGE_SECONDS = 60
PROCESSING_EXPORT_RECOVERY_AGE_SECONDS = TASK_HARD_TIME_LIMIT_SECONDS + 60
QUEUED_EXPORT_RECOVERY_BATCH_SIZE = 100
UNEXPECTED_EXPORT_FAILURE_CODE = "export_failed"
UNEXPECTED_EXPORT_FAILURE_MESSAGE = "导出失败，请稍后重试。"

SessionFactoryProvider = Callable[[], sessionmaker[Session]]
StorageFactory = Callable[[], JobStorage]


def _get_job_storage() -> JobStorage:
    settings = get_settings()
    return JobStorage(settings.storage_root, settings.max_upload_bytes)


SESSION_FACTORY_PROVIDER: SessionFactoryProvider = get_session_factory
STORAGE_FACTORY: StorageFactory = _get_job_storage


class PersistedExportFailure(RuntimeError):
    pass


class QueuedExportRecoveryError(RuntimeError):
    pass


def _process_export(task: Task, export_id: str) -> None:
    parsed_export_id = UUID(export_id)
    session_factory = SESSION_FACTORY_PROVIDER()
    bind = session_factory.kw.get("bind")
    if not isinstance(bind, Engine):
        raise RuntimeError("Export task session factory must be bound to an engine.")
    connection = bind.connect()
    session = session_factory(bind=connection)
    lock_key = _export_advisory_lock_key(parsed_export_id)
    claimed = False
    try:
        claimed = bool(
            connection.scalar(select(func.pg_try_advisory_lock(lock_key)))
        )
        if not claimed:
            return
        connection.commit()
        _process_claimed_export(task, session, parsed_export_id)
    finally:
        try:
            if session.in_transaction():
                session.rollback()
        finally:
            try:
                if claimed:
                    try:
                        connection.scalar(select(func.pg_advisory_unlock(lock_key)))
                    except Exception as error:
                        logger.error(
                            "export_advisory_unlock_failed",
                            extra={
                                "export_id": str(parsed_export_id),
                                "error_type": type(error).__name__,
                            },
                        )
                        connection.invalidate(error)
            finally:
                try:
                    session.close()
                finally:
                    connection.close()


def _process_claimed_export(task: Task, session: Session, export_id: UUID) -> None:
    try:
        _run_process_export_attempt(session, export_id)
    except PersistedExportFailure:
        raise
    except ExportError as error:
        status_after_failure = _persist_export_failure(
            session,
            export_id,
            error_code=error.code,
            error_message=error.public_message,
        )
        if status_after_failure == ExportStatus.COMPLETED:
            return
        _log_export_failure(export_id, error)
        raise PersistedExportFailure(error.public_message) from error
    except TerminalExportStateError as error:
        terminal = _get_export(session, export_id)
        if terminal is None or terminal.status == ExportStatus.COMPLETED:
            return
        if terminal.status == ExportStatus.FAILED:
            raise PersistedExportFailure(
                terminal.error_message or UNEXPECTED_EXPORT_FAILURE_MESSAGE
            ) from error
        raise
    except Exception as error:
        if task.request.retries < PROCESS_EXPORT_MAX_RETRIES:
            raise task.retry(
                exc=error,
                countdown=_retry_countdown(task.request.retries),
            ) from error
        status_after_failure = _persist_export_failure(
            session,
            export_id,
            error_code=UNEXPECTED_EXPORT_FAILURE_CODE,
            error_message=UNEXPECTED_EXPORT_FAILURE_MESSAGE,
        )
        if status_after_failure == ExportStatus.COMPLETED:
            return
        _log_export_failure(export_id, error)
        raise PersistedExportFailure(UNEXPECTED_EXPORT_FAILURE_MESSAGE) from error


process_export = cast(
    Any,
    celery_app.task(
        bind=True,
        name="text_verification.process_export",
        max_retries=PROCESS_EXPORT_MAX_RETRIES,
        acks_late=True,
        reject_on_worker_lost=True,
    )(_process_export),
)


def dispatch_recovered_export(export_id: str) -> None:
    process_export.delay(export_id)


def _recover_stale_queued_exports() -> list[str]:
    now = datetime.now(UTC)
    queued_cutoff = now - timedelta(seconds=QUEUED_EXPORT_RECOVERY_AGE_SECONDS)
    processing_cutoff = now - timedelta(
        seconds=PROCESSING_EXPORT_RECOVERY_AGE_SECONDS
    )
    session_factory = SESSION_FACTORY_PROVIDER()
    session = session_factory()
    try:
        export_ids = ExportRepository(session).list_stale_recoverable(
            queued_cutoff=queued_cutoff,
            processing_cutoff=processing_cutoff,
            limit=QUEUED_EXPORT_RECOVERY_BATCH_SIZE,
        )
    finally:
        session.close()

    dispatched: list[str] = []
    dispatch_failed = False
    for export_id in export_ids:
        serialized_export_id = str(export_id)
        try:
            dispatch_recovered_export(serialized_export_id)
        except Exception as error:
            dispatch_failed = True
            logger.error(
                "stale_queued_export_dispatch_failed",
                extra={
                    "export_id": serialized_export_id,
                    "error_type": type(error).__name__,
                },
            )
        else:
            dispatched.append(serialized_export_id)

    if dispatch_failed:
        raise QueuedExportRecoveryError("部分导出任务重新调度失败，将稍后重试。")
    return dispatched


recover_stale_queued_exports = cast(
    Any,
    celery_app.task(name="text_verification.recover_stale_queued_exports")(
        _recover_stale_queued_exports
    ),
)


def _run_process_export_attempt(session: Session, export_id: UUID) -> None:
    repository = ExportRepository(session)
    try:
        export = repository.get(export_id)
        if export is None or export.status == ExportStatus.COMPLETED:
            return
        if export.status == ExportStatus.FAILED:
            raise PersistedExportFailure(
                export.error_message or UNEXPECTED_EXPORT_FAILURE_MESSAGE
            )

        export = repository.mark_processing(export_id)
        session.commit()
        warnings = _render_export(session, export)
        repository.mark_completed(
            export_id,
            warnings=warnings,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise


def _render_export(session: Session, export: ExportRead) -> list[ExportWarning]:
    del session
    if export.expires_at <= datetime.now(UTC):
        raise ExportError("export_expired", "导出已过期，请重新创建。")
    snapshot = export.snapshot
    if snapshot is None:
        raise ExportError("export_snapshot_missing", "导出快照不存在，无法导出。")

    storage = STORAGE_FACTORY()
    source: Path | None = None
    if snapshot.source_type == FileType.DOCX:
        source = storage.source_path(export.job_id, FileType.DOCX)
        _verify_immutable_source(snapshot, source)

    plan = ReplacementPlanner().build(snapshot.document, snapshot.issues)
    if snapshot.source_type == FileType.DOCX:
        if source is None:
            raise ExportError("export_source_missing", "导出源文件不存在。")
        plan = DocxApplicabilityEvaluator().evaluate(
            source,
            snapshot.document,
            plan,
        )
    if plan.warnings != snapshot.preflight_warnings:
        raise ExportError("export_snapshot_mismatch", "导出快照校验失败，请重新创建。")

    extension = Path(export.file_name).suffix.removeprefix(".").lower()
    target = storage.export_path(export.job_id, export.export_id, extension)
    staging = target.with_name(f"{target.name}.{uuid4().hex}.building")

    try:
        warnings = _write_export(
            export=export,
            snapshot=snapshot,
            plan=plan,
            source=source,
            staging=staging,
        )
        if warnings != snapshot.preflight_warnings:
            raise ExportError(
                "export_snapshot_mismatch",
                "导出快照校验失败，请重新创建。",
            )
        try:
            staging.replace(target)
        except OSError as error:
            raise ExportError("export_write_failed", "无法保存导出文件。") from error
        return warnings
    except ExportError:
        raise
    finally:
        with suppress(FileNotFoundError):
            staging.unlink()


def _write_export(
    *,
    export: ExportRead,
    snapshot: ExportSnapshot,
    plan: ReplacementPlan,
    source: Path | None,
    staging: Path,
) -> list[ExportWarning]:
    if export.export_type == ExportType.MODIFIED_DOCUMENT:
        if snapshot.source_type == FileType.TXT:
            TxtExporter().export(snapshot.document, plan, staging)
            return plan.warnings
        if snapshot.source_type == FileType.DOCX:
            if source is None:
                raise ExportError("export_source_missing", "导出源文件不存在。")
            return DocxExporter().export(
                source,
                snapshot.document,
                plan,
                staging,
            ).warnings
        raise ExportError(
            "unsupported_export_type",
            "该文件类型不支持修改版导出。",
        )

    report_model = _build_report_model(snapshot=snapshot)
    report_exporter = ReportExporter()
    if export.export_type == ExportType.HTML_REPORT:
        report_exporter.render_html(report_model, staging)
        return plan.warnings
    if export.export_type == ExportType.PDF_REPORT:
        report_exporter.render_pdf(report_model, staging)
        return plan.warnings
    raise ExportError("unsupported_export_type", "不支持所选导出格式。")


def _build_report_model(
    *,
    snapshot: ExportSnapshot,
) -> ReportModel:
    return ReportModel(
        source_name=snapshot.source_name,
        generated_at=snapshot.captured_at,
        scenario=snapshot.scenario,
        enabled_categories=tuple(snapshot.enabled_categories),
        completed_categories=tuple(snapshot.completed_categories),
        failed_categories=tuple(
            ReportCategoryFailure(
                category=failure.category,
                code=failure.code,
                message=failure.message,
            )
            for failure in snapshot.checker_failures
        ),
        summary=ReportSummary(
            total_issues=snapshot.summary.total,
            by_category=snapshot.summary.by_category,
            by_severity=snapshot.summary.by_severity,
            by_decision=snapshot.summary.by_decision,
        ),
        issues=tuple(snapshot.issues),
        warnings=tuple(snapshot.preflight_warnings),
    )


def _verify_immutable_source(snapshot: ExportSnapshot, source: Path) -> None:
    expected_digest = snapshot.source_sha256
    if expected_digest is None or source.stat().st_size != snapshot.source_size_bytes:
        raise ExportError("export_source_changed", "导出源文件校验失败，请重新创建。")

    digest = sha256()
    with source.open("rb") as source_file:
        while chunk := source_file.read(1024 * 1024):
            digest.update(chunk)
    if digest.hexdigest() != expected_digest:
        raise ExportError("export_source_changed", "导出源文件校验失败，请重新创建。")


def _persist_export_failure(
    session: Session,
    export_id: UUID,
    *,
    error_code: str,
    error_message: str,
) -> ExportStatus | None:
    repository = ExportRepository(session)
    failed_export: ExportRead | None = None
    try:
        session.expire_all()
        current = repository.get(export_id)
        if current is None:
            return None
        if current.status in {ExportStatus.COMPLETED, ExportStatus.FAILED}:
            return current.status
        failed_export = repository.mark_failed(
            export_id,
            error_code=error_code,
            error_message=error_message,
        )
        session.commit()
    except TerminalExportStateError:
        session.rollback()
        current = repository.get(export_id)
        return None if current is None else current.status
    except Exception:
        session.rollback()
        raise

    _remove_failed_artifact(failed_export)
    return ExportStatus.FAILED


def _remove_failed_artifact(export: ExportRead) -> None:
    extension = Path(export.file_name).suffix.removeprefix(".").lower()
    try:
        path = STORAGE_FACTORY().export_path(
            export.job_id,
            export.export_id,
            extension,
        )
        with suppress(FileNotFoundError):
            path.unlink()
    except Exception as error:
        logger.warning(
            "failed_export_artifact_cleanup_failed",
            extra={
                "export_id": str(export.export_id),
                "job_id": str(export.job_id),
                "error_type": type(error).__name__,
            },
        )


def _get_export(session: Session, export_id: UUID) -> ExportRead | None:
    session.expire_all()
    return ExportRepository(session).get(export_id)


def _export_advisory_lock_key(export_id: UUID) -> int:
    digest = blake2b(export_id.bytes, digest_size=8, person=b"tv-export").digest()
    return int.from_bytes(digest, byteorder="big", signed=True)


def _retry_countdown(retries: int) -> int:
    return min(2**retries, PROCESS_EXPORT_RETRY_BACKOFF_CAP_SECONDS)


def _log_export_failure(export_id: UUID, error: Exception) -> None:
    logger.error(
        "process_export_failed",
        extra={
            "export_id": str(export_id),
            "error_type": type(error).__name__,
        },
    )
