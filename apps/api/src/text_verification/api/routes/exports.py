from __future__ import annotations

from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from text_verification.api.dependencies import (
    get_analysis_repository,
    get_db_session,
    get_job_repository,
    get_job_storage,
)
from text_verification.api.routes.analysis import (
    ANALYSIS_NOT_READY_CODE,
    _require_analysis,
    _require_ready_job,
)
from text_verification.api.routes.jobs import _http_error
from text_verification.domain.documents import FileType
from text_verification.domain.exports import ExportRead, ExportStatus, ExportType
from text_verification.infrastructure.analysis_repositories import AnalysisRepository
from text_verification.infrastructure.export_repository import ExportRepository
from text_verification.infrastructure.repositories import JobRepository
from text_verification.infrastructure.storage import InvalidUpload, JobStorage

EXPORT_DECISIONS_REQUIRED_CODE = "export_decisions_required"
EXPORT_CREATE_FAILED_CODE = "export_create_failed"
EXPORT_DISPATCH_FAILED_CODE = "export_dispatch_failed"
EXPORT_DISPATCH_RECOVERY_FAILED_CODE = "export_dispatch_recovery_failed"
EXPORT_EXPIRED_CODE = "export_expired"
EXPORT_FAILED_CODE = "export_failed"
EXPORT_FILE_UNAVAILABLE_CODE = "export_file_unavailable"
EXPORT_NOT_FOUND_CODE = "export_not_found"
EXPORT_NOT_READY_CODE = "export_not_ready"
UNSUPPORTED_EXPORT_TYPE_CODE = "unsupported_export_type"

REPORT_EXTENSIONS = {
    ExportType.HTML_REPORT: "html",
    ExportType.PDF_REPORT: "pdf",
}
DOWNLOAD_MEDIA_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "html": "text/html; charset=utf-8",
    "pdf": "application/pdf",
    "txt": "text/plain; charset=utf-8",
}

router = APIRouter(tags=["exports"])


class ExportCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1, max_length=32)


class ExportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    export_id: UUID
    job_id: UUID
    export_type: ExportType
    status: ExportStatus
    file_name: str
    warnings: list[str]
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime

    @classmethod
    def from_export(cls, export: ExportRead) -> ExportResponse:
        return cls(
            export_id=export.export_id,
            job_id=export.job_id,
            export_type=export.export_type,
            status=export.status,
            file_name=export.file_name,
            warnings=export.warnings,
            error_code=export.error_code,
            error_message=export.error_message,
            created_at=export.created_at,
            updated_at=export.updated_at,
            expires_at=export.expires_at,
        )


def dispatch_process_export(export_id: str) -> None:
    export_tasks = import_module("text_verification.workers.export_tasks")
    export_tasks.process_export.delay(export_id)


@router.post(
    "/jobs/{job_id}/exports",
    response_model=ExportResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_export(
    job_id: UUID,
    payload: ExportCreateRequest,
    session: Annotated[Session, Depends(get_db_session)],
    job_repository: Annotated[JobRepository, Depends(get_job_repository)],
    analysis_repository: Annotated[AnalysisRepository, Depends(get_analysis_repository)],
) -> ExportResponse:
    job = _require_ready_job(job_id, job_repository)
    _require_analysis(
        job_id,
        analysis_repository,
        missing_status_code=status.HTTP_409_CONFLICT,
        missing_code=ANALYSIS_NOT_READY_CODE,
        missing_message="分析结果尚未就绪，请稍后重试。",
    )
    export_type = _parse_export_type(payload.type)
    extension = _resolve_extension(job.file_type, export_type)

    try:
        job_repository.lock_job(job_id)
        if export_type == ExportType.MODIFIED_DOCUMENT:
            summary = analysis_repository.summarize_issues(job_id)
            if (
                summary.total > 0
                and summary.by_decision.get("unreviewed", 0) == summary.total
            ):
                raise _http_error(
                    status.HTTP_409_CONFLICT,
                    EXPORT_DECISIONS_REQUIRED_CODE,
                    "请先处理至少一个问题，再导出修改版文件。",
                )
        export = ExportRepository(session).create(job_id, export_type, extension)
        session.commit()
    except HTTPException:
        session.rollback()
        raise
    except Exception as error:
        session.rollback()
        raise _http_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            EXPORT_CREATE_FAILED_CODE,
            "创建导出任务失败，请稍后重试。",
        ) from error

    try:
        dispatch_process_export(str(export.export_id))
    except Exception as error:
        _recover_dispatch_failure(session, export.export_id)
        raise _http_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            EXPORT_DISPATCH_FAILED_CODE,
            "暂时无法开始导出，请稍后重试。",
        ) from error

    return ExportResponse.from_export(export)


@router.get(
    "/jobs/{job_id}/exports/{export_id}",
    response_model=ExportResponse,
)
def get_export_status(
    job_id: UUID,
    export_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
) -> ExportResponse:
    export = _require_export(session, job_id, export_id)
    return ExportResponse.from_export(export)


@router.get("/jobs/{job_id}/exports/{export_id}/download")
def download_export(
    job_id: UUID,
    export_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    storage: Annotated[JobStorage, Depends(get_job_storage)],
) -> FileResponse:
    export = _require_export(session, job_id, export_id)
    if export.expires_at <= datetime.now(UTC):
        raise _http_error(
            status.HTTP_410_GONE,
            EXPORT_EXPIRED_CODE,
            "导出文件已过期，请重新创建。",
        )
    if export.status == ExportStatus.FAILED:
        raise _http_error(
            status.HTTP_409_CONFLICT,
            EXPORT_FAILED_CODE,
            export.error_message or "导出失败，请稍后重试。",
        )
    if export.status != ExportStatus.COMPLETED:
        raise _http_error(
            status.HTTP_409_CONFLICT,
            EXPORT_NOT_READY_CODE,
            "导出文件尚未生成，请稍后重试。",
        )

    extension = Path(export.file_name).suffix.removeprefix(".").lower()
    try:
        export_path = storage.export_path(job_id, export_id, extension)
    except (InvalidUpload, ValueError) as error:
        raise _file_unavailable_error() from error
    if not export_path.is_file():
        raise _file_unavailable_error()

    encoded_name = quote(export.file_name, safe="")
    content_disposition = (
        f'attachment; filename="{export.file_name}"; '
        f"filename*=UTF-8''{encoded_name}"
    )
    return FileResponse(
        export_path,
        media_type=DOWNLOAD_MEDIA_TYPES[extension],
        headers={"Content-Disposition": content_disposition},
    )


def _parse_export_type(value: str) -> ExportType:
    try:
        return ExportType(value)
    except ValueError as error:
        raise _http_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            UNSUPPORTED_EXPORT_TYPE_CODE,
            "不支持所选导出格式。",
        ) from error


def _resolve_extension(file_type: FileType, export_type: ExportType) -> str:
    if export_type == ExportType.MODIFIED_DOCUMENT:
        if file_type not in {FileType.TXT, FileType.DOCX}:
            raise _http_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                UNSUPPORTED_EXPORT_TYPE_CODE,
                "该文件类型不支持所选导出格式。",
            )
        return file_type.value
    return REPORT_EXTENSIONS[export_type]


def _require_export(session: Session, job_id: UUID, export_id: UUID) -> ExportRead:
    export = ExportRepository(session).get_for_job(job_id, export_id)
    if export is None:
        raise _http_error(
            status.HTTP_404_NOT_FOUND,
            EXPORT_NOT_FOUND_CODE,
            "导出任务不存在。",
        )
    return export


def _recover_dispatch_failure(session: Session, export_id: UUID) -> None:
    repository = ExportRepository(session)
    try:
        repository.mark_failed(
            export_id,
            error_code=EXPORT_DISPATCH_FAILED_CODE,
            error_message="导出任务调度失败，请稍后重试。",
        )
        session.commit()
    except Exception as error:
        session.rollback()
        raise _http_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            EXPORT_DISPATCH_RECOVERY_FAILED_CODE,
            "导出任务调度失败且状态恢复未完成，请稍后重试。",
        ) from error


def _file_unavailable_error() -> HTTPException:
    return _http_error(
        status.HTTP_410_GONE,
        EXPORT_FILE_UNAVAILABLE_CODE,
        "导出文件不可用，请重新创建。",
    )
