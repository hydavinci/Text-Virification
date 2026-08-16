from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict

from text_verification.api.dependencies import get_analysis_repository, get_job_repository
from text_verification.api.routes.jobs import JOB_NOT_FOUND_CODE, _http_error
from text_verification.checkers.models import CHECK_CATEGORY_ORDER, CheckCategory, CheckerFailure
from text_verification.domain.documents import FileType, TextBlock
from text_verification.domain.issues import Issue, IssueSeverity
from text_verification.domain.jobs import JobRead, JobStatus
from text_verification.infrastructure.analysis_repositories import (
    AnalysisRepository,
    DocumentQuery,
    InvalidCursorError,
    IssueQuery,
)
from text_verification.infrastructure.repositories import JobRepository

ANALYSIS_NOT_FOUND_CODE = "analysis_not_found"
ANALYSIS_FAILED_CODE = "analysis_failed"
ANALYSIS_NOT_READY_CODE = "analysis_not_ready"
INVALID_ISSUE_FILTERS_CODE = "invalid_issue_filters"
JOB_EXPIRED_CODE = "job_expired"

ANALYSIS_FAILED_FALLBACK_MESSAGE = "分析失败，请重新上传文件后重试。"

READY_STATUSES = {JobStatus.COMPLETED, JobStatus.PARTIAL}
ISSUE_DECISIONS = Literal["accepted", "custom", "ignored", "pending"]

router = APIRouter(tags=["analysis"])


class CheckerFailurePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class DocumentPageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    status: JobStatus
    document_id: UUID
    file_type: FileType
    source_name: str
    version: int
    metadata: dict[str, object]
    blocks: list[TextBlock]
    total_blocks: int
    next_cursor: str | None
    checker_failures: dict[str, CheckerFailurePayload]


class IssuePageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    status: JobStatus
    total: int
    items: list[Issue]
    next_cursor: str | None
    checker_failures: dict[str, CheckerFailurePayload]


class AnalysisSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    status: JobStatus
    total_issues: int
    by_category: dict[str, int]
    by_severity: dict[str, int]
    checker_failures: dict[str, CheckerFailurePayload]


@router.get("/jobs/{job_id}/document", response_model=DocumentPageResponse)
def get_document_page(
    job_id: UUID,
    repository: Annotated[JobRepository, Depends(get_job_repository)],
    analysis_repository: Annotated[AnalysisRepository, Depends(get_analysis_repository)],
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> DocumentPageResponse:
    job = _require_ready_job(job_id, repository)
    try:
        page = analysis_repository.list_document_blocks(
            job_id,
            DocumentQuery(cursor=_normalize_cursor(cursor), limit=limit),
        )
    except InvalidCursorError as error:
        raise _http_error(status.HTTP_400_BAD_REQUEST, error.code, error.message) from error
    if page is None:
        raise _http_error(
            status.HTTP_404_NOT_FOUND,
            ANALYSIS_NOT_FOUND_CODE,
            "分析结果不存在，请重新上传后重试。",
        )
    return DocumentPageResponse(
        job_id=job_id,
        status=job.status,
        document_id=page.document_id,
        file_type=page.file_type,
        source_name=page.source_name,
        version=page.version,
        metadata=page.metadata,
        blocks=page.blocks,
        total_blocks=page.total_blocks,
        next_cursor=page.next_cursor,
        checker_failures=_serialize_checker_failures(
            analysis_repository.get_checker_failures(job_id)
        ),
    )


@router.get("/jobs/{job_id}/issues", response_model=IssuePageResponse)
def get_issue_page(
    job_id: UUID,
    repository: Annotated[JobRepository, Depends(get_job_repository)],
    analysis_repository: Annotated[AnalysisRepository, Depends(get_analysis_repository)],
    category: CheckCategory | None = None,
    severity: IssueSeverity | None = None,
    decision: ISSUE_DECISIONS | None = None,
    search: str | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> IssuePageResponse:
    job = _require_ready_job(job_id, repository)
    try:
        page = analysis_repository.list_issues(
            job_id,
            IssueQuery(
                category=category,
                severity=severity,
                decision=decision,
                search=search,
                cursor=_normalize_cursor(cursor),
                limit=limit,
            ),
        )
    except InvalidCursorError as error:
        raise _http_error(status.HTTP_400_BAD_REQUEST, error.code, error.message) from error
    except ValueError as error:
        raise _http_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            INVALID_ISSUE_FILTERS_CODE,
            "问题筛选条件无效，请刷新后重试。",
        ) from error
    return IssuePageResponse(
        job_id=job_id,
        status=job.status,
        total=page.total,
        items=page.items,
        next_cursor=page.next_cursor,
        checker_failures=_serialize_checker_failures(
            analysis_repository.get_checker_failures(job_id)
        ),
    )


@router.get("/jobs/{job_id}/summary", response_model=AnalysisSummaryResponse)
def get_analysis_summary(
    job_id: UUID,
    repository: Annotated[JobRepository, Depends(get_job_repository)],
    analysis_repository: Annotated[AnalysisRepository, Depends(get_analysis_repository)],
) -> AnalysisSummaryResponse:
    job = _require_ready_job(job_id, repository)
    summary = analysis_repository.summarize_issues(job_id)
    return AnalysisSummaryResponse(
        job_id=job_id,
        status=job.status,
        total_issues=summary.total,
        by_category={
            category.value: summary.by_category.get(category, 0)
            for category in CHECK_CATEGORY_ORDER
        },
        by_severity={
            severity.value: summary.by_severity.get(severity, 0)
            for severity in IssueSeverity
        },
        checker_failures=_serialize_checker_failures(
            analysis_repository.get_checker_failures(job_id)
        ),
    )


def _require_ready_job(job_id: UUID, repository: JobRepository) -> JobRead:
    job = repository.get_job(job_id)
    if job is None:
        raise _http_error(status.HTTP_404_NOT_FOUND, JOB_NOT_FOUND_CODE, "作业不存在。")
    if job.status == JobStatus.FAILED:
        raise _http_error(
            status.HTTP_409_CONFLICT,
            ANALYSIS_FAILED_CODE,
            job.error_message or ANALYSIS_FAILED_FALLBACK_MESSAGE,
        )
    if job.status == JobStatus.EXPIRED:
        raise _http_error(
            status.HTTP_410_GONE,
            JOB_EXPIRED_CODE,
            "作业已过期，请重新上传文件。",
        )
    if job.status not in READY_STATUSES:
        raise _http_error(
            status.HTTP_409_CONFLICT,
            ANALYSIS_NOT_READY_CODE,
            "分析结果尚未就绪，请稍后重试。",
        )
    return job


def _normalize_cursor(cursor: str | None) -> str | None:
    if cursor is None:
        return None
    normalized = cursor.strip()
    return normalized or None


def _serialize_checker_failures(
    failures: dict[CheckCategory, CheckerFailure],
) -> dict[str, CheckerFailurePayload]:
    return {
        category.value: CheckerFailurePayload(code=failure.code, message=failure.message)
        for category, failure in failures.items()
    }
