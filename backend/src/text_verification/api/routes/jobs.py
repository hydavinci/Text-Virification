from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from importlib import import_module
from typing import Annotated, BinaryIO
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from text_verification.api.dependencies import get_job_repository, get_job_storage
from text_verification.config import Settings, get_settings
from text_verification.domain.jobs import JobRead, JobStatus
from text_verification.infrastructure.repositories import JobRepository
from text_verification.infrastructure.storage import (
    InvalidUpload,
    JobStorage,
    UnsupportedFileType,
    UploadTooLarge,
)

logger = logging.getLogger(__name__)

DISPATCH_FAILURE_CODE = "job_dispatch_failed"
DISPATCH_RECOVERY_FAILURE_CODE = "job_dispatch_recovery_failed"
JOB_CREATE_FAILURE_CODE = "job_create_failed"
INVALID_UPLOAD_CODE = "invalid_upload"
UNSUPPORTED_FILE_TYPE_CODE = "unsupported_file_type"
UPLOAD_TOO_LARGE_CODE = "upload_too_large"

router = APIRouter(tags=["jobs"])


def dispatch_process_job(job_id: str) -> None:
    worker_tasks = import_module("text_verification.worker.tasks")
    process_job = worker_tasks.process_job

    process_job.delay(job_id)


@router.post("/jobs", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED)
def create_job(
    file: Annotated[UploadFile, File(...)],
    repository: Annotated[JobRepository, Depends(get_job_repository)],
    storage: Annotated[JobStorage, Depends(get_job_storage)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> JobRead:
    job_id = uuid4()
    file_name = file.filename or "upload"
    file_type_hint = _file_type_hint(file_name)
    stored_size: int | None = None
    now = datetime.now(UTC)

    try:
        stored = storage.save_stream(job_id, file_name, _binary_stream(file))
        stored_size = stored.size_bytes
        file_type_hint = stored.file_type.value
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
    except UploadTooLarge:
        repository.rollback()
        _cleanup_storage(job_id, storage)
        _log_failure(job_id, file_type_hint, stored_size, UPLOAD_TOO_LARGE_CODE)
        raise _http_error(
            status.HTTP_413_CONTENT_TOO_LARGE,
            UPLOAD_TOO_LARGE_CODE,
            "Upload exceeds the configured maximum size.",
        ) from None
    except UnsupportedFileType:
        repository.rollback()
        _cleanup_storage(job_id, storage)
        _log_failure(job_id, file_type_hint, stored_size, UNSUPPORTED_FILE_TYPE_CODE)
        raise _http_error(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            UNSUPPORTED_FILE_TYPE_CODE,
            "Upload file type is not supported.",
        ) from None
    except InvalidUpload:
        repository.rollback()
        _cleanup_storage(job_id, storage)
        _log_failure(job_id, file_type_hint, stored_size, INVALID_UPLOAD_CODE)
        raise _http_error(
            status.HTTP_400_BAD_REQUEST,
            INVALID_UPLOAD_CODE,
            "Upload content is invalid.",
        ) from None
    except HTTPException:
        raise
    except Exception:
        repository.rollback()
        _cleanup_storage(job_id, storage)
        _log_failure(job_id, file_type_hint, stored_size, JOB_CREATE_FAILURE_CODE)
        raise _http_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            JOB_CREATE_FAILURE_CODE,
            "Unable to create the job.",
        ) from None

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
    recovery_code = DISPATCH_FAILURE_CODE
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
        _cleanup_storage(job_id, storage)
    except Exception:
        repository.rollback()
        recovery_code = DISPATCH_RECOVERY_FAILURE_CODE

    _log_failure(job_id, file_type_hint, stored_size, recovery_code)
    raise _http_error(
        status.HTTP_503_SERVICE_UNAVAILABLE
        if recovery_code == DISPATCH_FAILURE_CODE
        else status.HTTP_500_INTERNAL_SERVER_ERROR,
        recovery_code,
        "Unable to dispatch the job for processing.",
    ) from None


def _cleanup_storage(job_id: UUID, storage: JobStorage) -> None:
    storage.delete_job(job_id)


def _binary_stream(file: UploadFile) -> BinaryIO:
    return file.file


def _file_type_hint(file_name: str) -> str | None:
    suffix = file_name.rsplit(".", 1)
    if len(suffix) != 2 or not suffix[1]:
        return None
    return suffix[1].lower()


def _http_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


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
