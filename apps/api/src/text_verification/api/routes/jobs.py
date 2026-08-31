from __future__ import annotations

import asyncio
import json
import logging
import ntpath
import posixpath
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from importlib import import_module
from time import monotonic
from typing import Annotated, BinaryIO, NoReturn
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, sessionmaker

from text_verification.api.dependencies import get_job_repository, get_job_storage
from text_verification.config import Settings, get_settings
from text_verification.domain.capabilities import default_capability_manifest
from text_verification.domain.documents import FileType
from text_verification.domain.jobs import TERMINAL_STATUSES, JobEvent, JobRead, JobStatus
from text_verification.infrastructure.database import get_session_factory
from text_verification.infrastructure.repositories import JobRepository
from text_verification.infrastructure.storage import (
    InvalidUpload,
    JobStorage,
    UnsupportedFileType,
    UploadCleanupFailed,
    UploadTooLarge,
)

logger = logging.getLogger(__name__)

DISPATCH_FAILURE_CODE = "job_dispatch_failed"
DISPATCH_CLEANUP_FAILURE_CODE = "job_dispatch_cleanup_failed"
DISPATCH_RECOVERY_FAILURE_CODE = "job_dispatch_recovery_failed"
JOB_CLEANUP_FAILURE_CODE = "job_cleanup_failed"
JOB_CREATE_FAILURE_CODE = "job_create_failed"
INVALID_UPLOAD_CODE = "invalid_upload"
INVALID_LAST_EVENT_ID_CODE = "invalid_last_event_id"
JOB_NOT_FOUND_CODE = "job_not_found"
UNSUPPORTED_FILE_TYPE_CODE = "unsupported_file_type"
UPLOAD_TOO_LARGE_CODE = "upload_too_large"
SSE_KEEPALIVE_SECONDS = 15.0
SSE_POLL_SECONDS = 0.5


router = APIRouter(tags=["jobs"])

SessionFactoryProvider = Callable[[], sessionmaker[Session]]
RepositoryFactory = Callable[[Session], JobRepository]

SESSION_FACTORY_PROVIDER: SessionFactoryProvider = get_session_factory
REPOSITORY_FACTORY: RepositoryFactory = JobRepository


class JobCleanupFailed(RuntimeError):
    pass


def dispatch_process_job(job_id: str) -> None:
    worker_tasks = import_module("text_verification.workers.tasks")
    process_job = worker_tasks.process_job
    process_job.delay(job_id)


@router.get("/jobs/{job_id}", response_model=JobRead)
def get_job(
    job_id: UUID,
    repository: Annotated[JobRepository, Depends(get_job_repository)],
) -> JobRead:
    job = repository.get_job(job_id)
    if job is None:
        raise _http_error(status.HTTP_404_NOT_FOUND, JOB_NOT_FOUND_CODE, "Job was not found.")
    return job


@router.get("/jobs/{job_id}/events")
async def stream_job_events(
    job_id: UUID,
    request: Request,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    after_sequence = _parse_last_event_id(last_event_id)
    return StreamingResponse(
        _job_event_stream(job_id, after_sequence, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/jobs", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED)
def create_job(
    file: Annotated[UploadFile, File(...)],
    repository: Annotated[JobRepository, Depends(get_job_repository)],
    storage: Annotated[JobStorage, Depends(get_job_storage)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> JobRead:
    job_id = uuid4()
    source_name = _normalize_source_name(file.filename or "upload")
    file_type_hint = _file_type_hint(source_name)
    stored_size: int | None = None
    now = datetime.now(UTC)

    try:
        stored = storage.save_stream(job_id, source_name, _binary_stream(file))
        stored_size = stored.size_bytes
        file_type_hint = stored.file_type.value
        _validate_declared_mime(file.content_type, stored.file_type.value)
        job = repository.create_job(
            job_id=job_id,
            source_name=stored.original_name,
            file_type=stored.file_type.value,
            size_bytes=stored.size_bytes,
            storage_key=str(job_id),
            created_at=now,
            expires_at=now + timedelta(hours=settings.job_retention_hours),
        )
        repository.commit()
    except UploadCleanupFailed:
        repository.rollback()
        _raise_failure(
            job_id,
            file_type_hint,
            stored_size,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            JOB_CLEANUP_FAILURE_CODE,
            "Unable to recover from the failed upload.",
        )
    except UploadTooLarge:
        repository.rollback()
        _raise_failure_after_cleanup(
            job_id,
            storage,
            file_type_hint,
            stored_size,
            status.HTTP_413_CONTENT_TOO_LARGE,
            UPLOAD_TOO_LARGE_CODE,
            "Upload exceeds the configured maximum size.",
        )
    except UnsupportedFileType:
        repository.rollback()
        _raise_failure_after_cleanup(
            job_id,
            storage,
            file_type_hint,
            stored_size,
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            UNSUPPORTED_FILE_TYPE_CODE,
            "Upload file type is not supported.",
        )
    except InvalidUpload:
        repository.rollback()
        _raise_failure_after_cleanup(
            job_id,
            storage,
            file_type_hint,
            stored_size,
            status.HTTP_400_BAD_REQUEST,
            INVALID_UPLOAD_CODE,
            "Upload content is invalid.",
        )
    except HTTPException:
        raise
    except Exception:
        repository.rollback()
        _raise_failure_after_cleanup(
            job_id,
            storage,
            file_type_hint,
            stored_size,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            JOB_CREATE_FAILURE_CODE,
            "Unable to create the job.",
        )

    try:
        dispatch_process_job(str(job_id))
    except Exception:
        return _recover_from_dispatch_failure(
            job_id,
            repository,
            storage,
            file_type_hint,
            stored_size,
        )

    return job


def _recover_from_dispatch_failure(
    job_id: UUID,
    repository: JobRepository,
    storage: JobStorage,
    file_type_hint: str | None,
    stored_size: int | None,
) -> JobRead:
    try:
        repository.transition(
            job_id,
            JobStatus.FAILED,
            0,
            "作业调度失败",
            error_code=DISPATCH_FAILURE_CODE,
            error_message="Job dispatch failed.",
        )
        repository.commit()
    except Exception:
        repository.rollback()
        _raise_failure(
            job_id,
            file_type_hint,
            stored_size,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            DISPATCH_RECOVERY_FAILURE_CODE,
            "Unable to recover from the dispatch failure.",
        )

    try:
        _cleanup_storage(job_id, storage)
    except JobCleanupFailed:
        _raise_failure(
            job_id,
            file_type_hint,
            stored_size,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            DISPATCH_CLEANUP_FAILURE_CODE,
            "Unable to clean up the failed dispatched job.",
        )

    _raise_failure(
        job_id,
        file_type_hint,
        stored_size,
        status.HTTP_503_SERVICE_UNAVAILABLE,
        DISPATCH_FAILURE_CODE,
        "Unable to dispatch the job for processing.",
    )


def _cleanup_storage(job_id: UUID, storage: JobStorage) -> None:
    try:
        storage.delete_job(job_id)
    except Exception as cleanup_error:
        raise JobCleanupFailed("Failed to clean up the uploaded job directory.") from cleanup_error


def _binary_stream(file: UploadFile) -> BinaryIO:
    return file.file


def _validate_declared_mime(content_type: str | None, file_type: str) -> None:
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    if not normalized or normalized == "application/octet-stream":
        return
    capability = default_capability_manifest().for_type(FileType(file_type))
    if normalized not in capability.mime_types:
        raise UnsupportedFileType("Declared MIME type does not match upload content.")


def _parse_last_event_id(last_event_id: str | None) -> int:
    if last_event_id is None:
        return 0
    try:
        parsed = int(last_event_id)
    except ValueError as error:
        raise _http_error(
            status.HTTP_400_BAD_REQUEST,
            INVALID_LAST_EVENT_ID_CODE,
            "Last-Event-ID must be a non-negative integer.",
        ) from error
    if parsed < 0:
        raise _http_error(
            status.HTTP_400_BAD_REQUEST,
            INVALID_LAST_EVENT_ID_CODE,
            "Last-Event-ID must be a non-negative integer.",
        )
    return parsed


async def _job_event_stream(
    job_id: UUID,
    after_sequence: int,
    request: Request,
) -> AsyncIterator[str]:
    session_factory = SESSION_FACTORY_PROVIDER()
    last_keepalive = monotonic()

    while True:
        if await request.is_disconnected():
            return

        events, job = _poll_job_state(session_factory, job_id, after_sequence)
        emitted = False
        for event in events:
            yield _format_progress_event(event)
            after_sequence = event.sequence
            last_keepalive = monotonic()
            emitted = True

        if job is None or job.status == JobStatus.EXPIRED:
            yield _format_control_event("expired")
            return

        if job.status in TERMINAL_STATUSES:
            yield _format_control_event("done")
            return

        if not emitted and monotonic() - last_keepalive >= SSE_KEEPALIVE_SECONDS:
            yield ": keepalive\n\n"
            last_keepalive = monotonic()

        await asyncio.sleep(SSE_POLL_SECONDS)


def _poll_job_state(
    session_factory: sessionmaker[Session],
    job_id: UUID,
    after_sequence: int,
) -> tuple[list[JobEvent], JobRead | None]:
    session = session_factory()
    try:
        repository = REPOSITORY_FACTORY(session)
        job = repository.get_job(job_id)
        events = repository.list_events_after(job_id, after_sequence)
        return events, job
    finally:
        session.close()


def _format_progress_event(event: JobEvent) -> str:
    payload = json.dumps(
        {
            "status": event.status.value,
            "progress": event.progress,
            "message": event.message,
            "created_at": event.created_at.isoformat(),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"id: {event.sequence}\nevent: progress\ndata: {payload}\n\n"


def _format_control_event(event_name: str) -> str:
    payload = json.dumps({"event": event_name}, separators=(",", ":"))
    return f"event: {event_name}\ndata: {payload}\n\n"


def _normalize_source_name(file_name: str) -> str:
    posix_name = posixpath.basename(file_name)
    normalized = ntpath.basename(posix_name)
    return normalized or "upload"


def _file_type_hint(file_name: str) -> str | None:
    suffix = file_name.rsplit(".", 1)
    if len(suffix) != 2 or not suffix[1]:
        return None
    return suffix[1].lower()


def _http_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _raise_failure_after_cleanup(
    job_id: UUID,
    storage: JobStorage,
    file_type_hint: str | None,
    stored_size: int | None,
    status_code: int,
    error_code: str,
    message: str,
) -> NoReturn:
    try:
        _cleanup_storage(job_id, storage)
    except JobCleanupFailed:
        _raise_failure(
            job_id,
            file_type_hint,
            stored_size,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            JOB_CLEANUP_FAILURE_CODE,
            "Unable to recover from the failed upload.",
        )

    _raise_failure(job_id, file_type_hint, stored_size, status_code, error_code, message)


def _raise_failure(
    job_id: UUID,
    file_type: str | None,
    byte_size: int | None,
    status_code: int,
    error_code: str,
    message: str,
) -> NoReturn:
    _log_failure(job_id, file_type, byte_size, error_code)
    raise _http_error(status_code, error_code, message) from None


def _log_failure(
    job_id: UUID,
    file_type: str | None,
    byte_size: int | None,
    error_code: str,
) -> None:
    logger.warning(
        "job_request_failed",
        extra={
            "job_id": str(job_id),
            "file_type": file_type,
            "byte_size": byte_size,
            "error_code": error_code,
        },
    )
