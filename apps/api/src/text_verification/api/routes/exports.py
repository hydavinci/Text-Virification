from __future__ import annotations

import logging
from datetime import UTC, datetime
from hashlib import sha256
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
    ANALYSIS_FAILED_CODE,
    ANALYSIS_FAILED_FALLBACK_MESSAGE,
    ANALYSIS_NOT_READY_CODE,
    JOB_EXPIRED_CODE,
    READY_STATUSES,
    _require_analysis,
)
from text_verification.api.routes.jobs import JOB_NOT_FOUND_CODE, _http_error
from text_verification.checkers.models import CheckCategory, CheckScenario
from text_verification.domain.documents import FileType
from text_verification.domain.exports import (
    MAX_EXPORT_SNAPSHOT_BYTES,
    ExportCheckerFailureSnapshot,
    ExportDispatchStatus,
    ExportIssueSummarySnapshot,
    ExportPublicRead,
    ExportRead,
    ExportSnapshot,
    ExportSnapshotTooLarge,
    ExportStatus,
    ExportType,
    ExportWarning,
)
from text_verification.domain.jobs import JobStatus
from text_verification.exporters import DocxApplicabilityEvaluator, ReplacementPlanner
from text_verification.infrastructure.analysis_repositories import AnalysisRepository
from text_verification.infrastructure.export_repository import ExportRepository
from text_verification.infrastructure.orm import JobRow
from text_verification.infrastructure.repositories import JobRepository
from text_verification.infrastructure.storage import InvalidUpload, JobStorage

EXPORT_DECISIONS_REQUIRED_CODE = "export_decisions_required"
EXPORT_CREATE_FAILED_CODE = "export_create_failed"
EXPORT_CONFIRMATION_REQUIRED_CODE = "export_confirmation_required"
EXPORT_EXPIRED_CODE = "export_expired"
EXPORT_FAILED_CODE = "export_failed"
EXPORT_FILE_UNAVAILABLE_CODE = "export_file_unavailable"
EXPORT_NOT_FOUND_CODE = "export_not_found"
EXPORT_NOT_READY_CODE = "export_not_ready"
EXPORT_SNAPSHOT_TOO_LARGE_CODE = "export_snapshot_too_large"
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
logger = logging.getLogger(__name__)


class ExportCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1, max_length=32)
    confirm_warnings: bool = False


class ExportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    export_id: UUID
    job_id: UUID
    export_type: ExportType
    status: ExportStatus
    file_name: str
    warnings: list[ExportWarning]
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime

    @classmethod
    def from_export(cls, export: ExportRead | ExportPublicRead) -> ExportResponse:
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


class ExportCreateResponse(ExportResponse):
    dispatch_status: ExportDispatchStatus

    @classmethod
    def from_created_export(
        cls,
        export: ExportRead,
        *,
        dispatch_status: ExportDispatchStatus,
    ) -> ExportCreateResponse:
        response = ExportResponse.from_export(export)
        return cls(
            **response.model_dump(),
            dispatch_status=dispatch_status,
        )


def dispatch_process_export(export_id: str) -> None:
    export_tasks = import_module("text_verification.workers.export_tasks")
    export_tasks.process_export.delay(export_id)


@router.post(
    "/jobs/{job_id}/exports",
    response_model=ExportCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_export(
    job_id: UUID,
    payload: ExportCreateRequest,
    session: Annotated[Session, Depends(get_db_session)],
    job_repository: Annotated[JobRepository, Depends(get_job_repository)],
    analysis_repository: Annotated[AnalysisRepository, Depends(get_analysis_repository)],
    storage: Annotated[JobStorage, Depends(get_job_storage)],
) -> ExportCreateResponse:
    try:
        job = _lock_ready_job(job_id, job_repository)
        _require_analysis(
            job_id,
            analysis_repository,
            missing_status_code=status.HTTP_409_CONFLICT,
            missing_code=ANALYSIS_NOT_READY_CODE,
            missing_message="分析结果尚未就绪，请稍后重试。",
        )
        export_type = _parse_export_type(payload.type)
        file_type = FileType(job.file_type)
        extension = _resolve_extension(file_type, export_type)
        document = analysis_repository.get_document(job_id)
        if document is None:
            raise _http_error(
                status.HTTP_409_CONFLICT,
                ANALYSIS_NOT_READY_CODE,
                "分析结果尚未就绪，请稍后重试。",
            )
        issues = analysis_repository.list_all_issues(job_id)
        summary = analysis_repository.summarize_issues(job_id)
        if export_type == ExportType.MODIFIED_DOCUMENT:
            if (
                summary.total > 0
                and summary.by_decision.get("unreviewed", 0) == summary.total
            ):
                raise _http_error(
                    status.HTTP_409_CONFLICT,
                    EXPORT_DECISIONS_REQUIRED_CODE,
                    "请先处理至少一个问题，再导出修改版文件。",
                )
        plan = ReplacementPlanner().build(document, issues)
        source_sha256: str | None = None
        source_size_bytes = job.size_bytes
        if file_type == FileType.DOCX:
            source = storage.source_path(job_id, file_type)
            source_sha256 = _sha256_file(source)
            source_size_bytes = source.stat().st_size
            plan = DocxApplicabilityEvaluator().evaluate(source, document, plan)
        if (
            export_type == ExportType.MODIFIED_DOCUMENT
            and file_type == FileType.DOCX
            and plan.warnings
            and not payload.confirm_warnings
        ):
            raise _confirmation_required(plan.warnings)

        failures = analysis_repository.get_checker_failures(job_id)
        enabled_categories = [
            CheckCategory(category) for category in job.enabled_categories_json
        ]
        captured_at = datetime.now(UTC)
        snapshot = ExportSnapshot(
            captured_at=captured_at,
            source_name=job.source_name,
            source_type=file_type,
            source_size_bytes=source_size_bytes,
            source_sha256=source_sha256,
            scenario=CheckScenario(job.scenario),
            enabled_categories=enabled_categories,
            completed_categories=[
                category for category in enabled_categories if category not in failures
            ],
            checker_failures=[
                ExportCheckerFailureSnapshot(
                    category=category,
                    code=failures[category].code,
                    message=failures[category].message,
                )
                for category in enabled_categories
                if category in failures
            ],
            summary=ExportIssueSummarySnapshot(
                total=summary.total,
                by_category=summary.by_category,
                by_severity=summary.by_severity,
                by_decision=summary.by_decision,
            ),
            document=document,
            issues=issues,
            preflight_warnings=plan.warnings,
        )
        export = ExportRepository(session).create(
            job_id,
            export_type,
            extension,
            snapshot=snapshot,
            warnings=plan.warnings,
            expires_at=job.expires_at,
            maximum_snapshot_bytes=MAX_EXPORT_SNAPSHOT_BYTES,
        )
        session.commit()
    except HTTPException:
        session.rollback()
        raise
    except ExportSnapshotTooLarge as error:
        session.rollback()
        raise _http_error(
            status.HTTP_413_CONTENT_TOO_LARGE,
            EXPORT_SNAPSHOT_TOO_LARGE_CODE,
            "导出快照过大，无法创建导出；请缩小文档或问题数量后重试。",
        ) from error
    except Exception as error:
        session.rollback()
        logger.exception(
            "export_create_failed",
            extra={
                "job_id": str(job_id),
                "error_type": type(error).__name__,
            },
        )
        raise _http_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            EXPORT_CREATE_FAILED_CODE,
            "创建导出任务失败，请稍后重试。",
        ) from error

    dispatch_status = ExportDispatchStatus.DISPATCHED
    try:
        dispatch_process_export(str(export.export_id))
    except Exception as error:
        dispatch_status = ExportDispatchStatus.DEFERRED
        logger.error(
            "export_dispatch_deferred",
            extra={
                "export_id": str(export.export_id),
                "job_id": str(job_id),
                "error_type": type(error).__name__,
            },
        )

    return ExportCreateResponse.from_created_export(
        export,
        dispatch_status=dispatch_status,
    )


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


def _lock_ready_job(job_id: UUID, repository: JobRepository) -> JobRow:
    try:
        job = repository.lock_job(job_id)
    except LookupError as error:
        raise _http_error(
            status.HTTP_404_NOT_FOUND,
            JOB_NOT_FOUND_CODE,
            "作业不存在。",
        ) from error

    job_status = JobStatus(job.status)
    if job_status == JobStatus.FAILED:
        raise _http_error(
            status.HTTP_409_CONFLICT,
            ANALYSIS_FAILED_CODE,
            job.error_message or ANALYSIS_FAILED_FALLBACK_MESSAGE,
        )
    if job_status == JobStatus.EXPIRED or job.expires_at <= datetime.now(UTC):
        raise _http_error(
            status.HTTP_410_GONE,
            JOB_EXPIRED_CODE,
            "作业已过期，请重新上传文件。",
        )
    if job_status not in READY_STATUSES:
        raise _http_error(
            status.HTTP_409_CONFLICT,
            ANALYSIS_NOT_READY_CODE,
            "分析结果尚未就绪，请稍后重试。",
        )
    return job


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


def _require_export(
    session: Session,
    job_id: UUID,
    export_id: UUID,
) -> ExportPublicRead:
    export = ExportRepository(session).get_for_job(job_id, export_id)
    if export is None:
        raise _http_error(
            status.HTTP_404_NOT_FOUND,
            EXPORT_NOT_FOUND_CODE,
            "导出任务不存在。",
        )
    return export


def _confirmation_required(warnings: list[ExportWarning]) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": EXPORT_CONFIRMATION_REQUIRED_CODE,
            "message": "检测到无法自动应用的 DOCX 修改，请确认警告后重试。",
            "warnings": [warning.model_dump(mode="json") for warning in warnings],
        },
    )


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _file_unavailable_error() -> HTTPException:
    return _http_error(
        status.HTTP_410_GONE,
        EXPORT_FILE_UNAVAILABLE_CODE,
        "导出文件不可用，请重新创建。",
    )
