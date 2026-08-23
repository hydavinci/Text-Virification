from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from importlib import import_module
from time import monotonic
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, sessionmaker

from text_verification.api.dependencies import (
    get_analysis_repository,
    get_db_session,
    get_job_repository,
    get_revision_repository,
)
from text_verification.api.routes.analysis import (
    ANALYSIS_FAILED_CODE,
    ANALYSIS_FAILED_FALLBACK_MESSAGE,
    ANALYSIS_NOT_FOUND_CODE,
    ANALYSIS_NOT_FOUND_MESSAGE,
    ANALYSIS_NOT_READY_CODE,
    JOB_EXPIRED_CODE,
    READY_STATUSES,
)
from text_verification.api.routes.jobs import (
    JOB_NOT_FOUND_CODE,
    SSE_KEEPALIVE_SECONDS,
    SSE_POLL_SECONDS,
    _format_control_event,
    _http_error,
    _parse_last_event_id,
)
from text_verification.domain.derived_content import (
    DerivedContentValidationError,
    DiffSegment,
    derive_document,
    myers_diff,
)
from text_verification.domain.documents import TextBlock
from text_verification.domain.jobs import JobRead, JobStatus
from text_verification.domain.revisions import (
    DocumentVersionEvent,
    DocumentVersionRead,
    DocumentVersionStatus,
    DraftBlock,
    EditDraftRead,
)
from text_verification.infrastructure.analysis_repositories import AnalysisRepository
from text_verification.infrastructure.database import get_session_factory
from text_verification.infrastructure.repositories import JobRepository
from text_verification.infrastructure.revision_repository import (
    DraftConsumedError,
    DraftNotFoundError,
    InvalidBaseVersionError,
    InvalidDraftBlocksError,
    RevisionRepository,
    StaleDraftRevisionError,
    VersionNotFoundError,
)

DRAFT_NOT_FOUND_CODE = "draft_not_found"
INVALID_BASE_VERSION_CODE = "invalid_base_version"
INVALID_DRAFT_BLOCKS_CODE = "invalid_draft_blocks"
STALE_DRAFT_REVISION_CODE = "stale_draft_revision"
VERSION_NOT_FOUND_CODE = "version_not_found"
VERSION_NOT_FOUND_MESSAGE = "文档版本不存在。"
DISPATCH_RECOVERY_MAX_ATTEMPTS = 3
DerivedView = Literal["modified", "diff"]

router = APIRouter(tags=["versions"])

SessionFactoryProvider = Callable[[], sessionmaker[Session]]
RevisionRepositoryFactory = Callable[[Session], RevisionRepository]

SESSION_FACTORY_PROVIDER: SessionFactoryProvider = get_session_factory
REVISION_REPOSITORY_FACTORY: RevisionRepositoryFactory = RevisionRepository


class VersionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    active_version_id: UUID | None = None
    versions: list[DocumentVersionRead]


class DraftCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_version_id: UUID


class DraftUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    blocks: list[DraftBlock]


class DraftReanalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_draft_revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=255)


class DraftReanalysisResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: DocumentVersionRead
    events_url: str


class DerivedDiffBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_id: str
    segments: list[DiffSegment]


class DerivedContentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    version_id: UUID
    decision_snapshot_sha256: str
    blocks: list[TextBlock] | list[DerivedDiffBlock]


class ReanalysisDispatchRecoveryError(RuntimeError):
    pass


@router.get("/jobs/{job_id}/versions", response_model=VersionListResponse)
def list_versions(
    job_id: UUID,
    job_repository: Annotated[JobRepository, Depends(get_job_repository)],
    revision_repository: Annotated[RevisionRepository, Depends(get_revision_repository)],
) -> VersionListResponse:
    _require_job(job_id, job_repository)
    active_version = revision_repository.get_active_version(job_id)
    return VersionListResponse(
        job_id=job_id,
        active_version_id=None if active_version is None else active_version.version_id,
        versions=revision_repository.list_versions(job_id),
    )


@router.get("/jobs/{job_id}/versions/{version_id}/events")
async def stream_version_events(
    job_id: UUID,
    version_id: UUID,
    request: Request,
    job_repository: Annotated[JobRepository, Depends(get_job_repository)],
    revision_repository: Annotated[RevisionRepository, Depends(get_revision_repository)],
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    _require_job(job_id, job_repository)
    _require_version(job_id, version_id, revision_repository)
    after_sequence = _parse_last_event_id(last_event_id)
    return StreamingResponse(
        _version_event_stream(version_id, after_sequence, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/jobs/{job_id}/versions/{version_id}/derived",
    response_model=DerivedContentResponse,
)
def get_derived_content(
    job_id: UUID,
    version_id: UUID,
    job_repository: Annotated[JobRepository, Depends(get_job_repository)],
    analysis_repository: Annotated[AnalysisRepository, Depends(get_analysis_repository)],
    revision_repository: Annotated[RevisionRepository, Depends(get_revision_repository)],
    view: DerivedView = "modified",
) -> DerivedContentResponse:
    job = _require_job(job_id, job_repository)
    _require_ready_status(job)
    version = _require_succeeded_version(job_id, version_id, revision_repository)
    document = analysis_repository.get_document(job_id, version.version_id)
    if document is None:
        raise _http_error(
            status.HTTP_404_NOT_FOUND,
            ANALYSIS_NOT_FOUND_CODE,
            ANALYSIS_NOT_FOUND_MESSAGE,
        )

    issues = analysis_repository.list_all_issues(job_id, version.version_id)
    try:
        derived = derive_document(version.version_id, document, issues)
    except DerivedContentValidationError as error:
        raise _derived_content_conflict(error) from error
    if view == "modified":
        blocks: list[TextBlock] | list[DerivedDiffBlock] = derived.document.blocks
    else:
        blocks = [
            DerivedDiffBlock(
                block_id=original_block.block_id,
                segments=list(myers_diff(original_block.text, derived_block.text)),
            )
            for original_block, derived_block in zip(
                document.blocks,
                derived.document.blocks,
                strict=True,
            )
        ]
    return DerivedContentResponse(
        job_id=job_id,
        version_id=version.version_id,
        decision_snapshot_sha256=derived.decision_snapshot_sha256,
        blocks=blocks,
    )


@router.post("/jobs/{job_id}/drafts", response_model=EditDraftRead)
def create_draft(
    job_id: UUID,
    payload: DraftCreateRequest,
    session: Annotated[Session, Depends(get_db_session)],
    job_repository: Annotated[JobRepository, Depends(get_job_repository)],
    revision_repository: Annotated[RevisionRepository, Depends(get_revision_repository)],
) -> EditDraftRead:
    _lock_job(job_id, job_repository)
    try:
        draft = revision_repository.create_draft(job_id, payload.base_version_id)
        session.commit()
    except VersionNotFoundError as error:
        session.rollback()
        raise _http_error(
            status.HTTP_404_NOT_FOUND,
            VERSION_NOT_FOUND_CODE,
            VERSION_NOT_FOUND_MESSAGE,
        ) from error
    except InvalidBaseVersionError as error:
        session.rollback()
        raise _http_error(
            status.HTTP_409_CONFLICT,
            INVALID_BASE_VERSION_CODE,
            "只能基于成功版本创建草稿。",
        ) from error
    except Exception:
        session.rollback()
        raise
    return draft


@router.get("/jobs/{job_id}/drafts/{draft_id}", response_model=EditDraftRead)
def get_draft(
    job_id: UUID,
    draft_id: UUID,
    job_repository: Annotated[JobRepository, Depends(get_job_repository)],
    revision_repository: Annotated[RevisionRepository, Depends(get_revision_repository)],
) -> EditDraftRead:
    _require_job(job_id, job_repository)
    draft = revision_repository.get_draft(job_id, draft_id)
    if draft is None:
        raise _http_error(
            status.HTTP_404_NOT_FOUND,
            DRAFT_NOT_FOUND_CODE,
            "草稿不存在。",
        )
    return draft


@router.put("/jobs/{job_id}/drafts/{draft_id}", response_model=EditDraftRead)
def update_draft(
    job_id: UUID,
    draft_id: UUID,
    payload: DraftUpdateRequest,
    session: Annotated[Session, Depends(get_db_session)],
    job_repository: Annotated[JobRepository, Depends(get_job_repository)],
    revision_repository: Annotated[RevisionRepository, Depends(get_revision_repository)],
) -> EditDraftRead:
    _lock_job(job_id, job_repository)
    try:
        draft = revision_repository.update_draft(
            job_id,
            draft_id,
            expected_revision=payload.expected_revision,
            blocks=payload.blocks,
        )
        session.commit()
    except DraftNotFoundError as error:
        session.rollback()
        raise _http_error(
            status.HTTP_404_NOT_FOUND,
            DRAFT_NOT_FOUND_CODE,
            "草稿不存在。",
        ) from error
    except DraftConsumedError as error:
        session.rollback()
        raise _draft_consumed_conflict() from error
    except StaleDraftRevisionError as error:
        session.rollback()
        raise _draft_conflict(error.current_revision) from error
    except InvalidDraftBlocksError as error:
        session.rollback()
        raise _invalid_draft_blocks(error) from error
    except Exception:
        session.rollback()
        raise
    return draft


@router.delete("/jobs/{job_id}/drafts/{draft_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_draft(
    job_id: UUID,
    draft_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    job_repository: Annotated[JobRepository, Depends(get_job_repository)],
    revision_repository: Annotated[RevisionRepository, Depends(get_revision_repository)],
) -> Response:
    _lock_job(job_id, job_repository)
    try:
        revision_repository.delete_draft(job_id, draft_id)
        session.commit()
    except DraftNotFoundError as error:
        session.rollback()
        raise _http_error(
            status.HTTP_404_NOT_FOUND,
            DRAFT_NOT_FOUND_CODE,
            "草稿不存在。",
        ) from error
    except DraftConsumedError as error:
        session.rollback()
        raise _draft_consumed_conflict() from error
    except Exception:
        session.rollback()
        raise
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/jobs/{job_id}/drafts/{draft_id}/reanalyze",
    response_model=DraftReanalysisResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def reanalyze_draft(
    job_id: UUID,
    draft_id: UUID,
    payload: DraftReanalysisRequest,
    session: Annotated[Session, Depends(get_db_session)],
    job_repository: Annotated[JobRepository, Depends(get_job_repository)],
    revision_repository: Annotated[RevisionRepository, Depends(get_revision_repository)],
) -> DraftReanalysisResponse:
    _lock_reanalysis_job(job_id, job_repository)
    if revision_repository.get_draft(job_id, draft_id) is None:
        raise _http_error(
            status.HTTP_404_NOT_FOUND,
            DRAFT_NOT_FOUND_CODE,
            "草稿不存在。",
        )
    try:
        creation = revision_repository.create_reanalysis_version(
            draft_id,
            expected_draft_revision=payload.expected_draft_revision,
            idempotency_key=payload.idempotency_key,
        )
        session.commit()
    except DraftNotFoundError as error:
        session.rollback()
        raise _http_error(
            status.HTTP_404_NOT_FOUND,
            DRAFT_NOT_FOUND_CODE,
            "草稿不存在。",
        ) from error
    except DraftConsumedError as error:
        session.rollback()
        raise _draft_consumed_conflict() from error
    except StaleDraftRevisionError as error:
        session.rollback()
        raise _draft_conflict(error.current_revision) from error
    except InvalidBaseVersionError as error:
        session.rollback()
        raise _http_error(
            status.HTTP_409_CONFLICT,
            INVALID_BASE_VERSION_CODE,
            "只能基于成功版本创建草稿。",
        ) from error
    except Exception:
        session.rollback()
        raise

    version = creation.version
    if creation.created:
        try:
            dispatch_process_document_version(str(version.version_id))
        except Exception as error:
            try:
                _recover_from_reanalysis_dispatch_failure(
                    session,
                    revision_repository,
                    version.version_id,
                )
            except ReanalysisDispatchRecoveryError as recovery_error:
                raise _http_error(
                    status.HTTP_500_INTERNAL_SERVER_ERROR,
                    "reanalysis_dispatch_recovery_failed",
                    "重新分析调度失败且状态恢复未完成，请稍后重试。",
                ) from recovery_error
            raise _http_error(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "reanalysis_dispatch_failed",
                "重新分析调度失败，请稍后重试。",
            ) from error

    return DraftReanalysisResponse(
        version=version,
        events_url=f"/api/v1/jobs/{job_id}/versions/{version.version_id}/events",
    )


def _lock_job(job_id: UUID, repository: JobRepository) -> None:
    try:
        repository.lock_job(job_id)
    except LookupError as error:
        raise _http_error(
            status.HTTP_404_NOT_FOUND,
            JOB_NOT_FOUND_CODE,
            "作业不存在。",
        ) from error


def _lock_reanalysis_job(job_id: UUID, repository: JobRepository) -> None:
    try:
        job = repository.lock_job(job_id)
    except LookupError as error:
        raise _http_error(
            status.HTTP_404_NOT_FOUND,
            JOB_NOT_FOUND_CODE,
            "作业不存在。",
        ) from error
    if JobStatus(job.status) == JobStatus.EXPIRED or job.expires_at <= datetime.now(UTC):
        raise _http_error(
            status.HTTP_410_GONE,
            JOB_EXPIRED_CODE,
            "作业已过期，请重新上传文件。",
        )


def _require_job(job_id: UUID, repository: JobRepository) -> JobRead:
    job = repository.get_job(job_id)
    if job is None:
        raise _http_error(
            status.HTTP_404_NOT_FOUND,
            JOB_NOT_FOUND_CODE,
            "作业不存在。",
        )
    return job


def _require_ready_status(job: JobRead) -> None:
    if job.status == JobStatus.FAILED:
        raise _http_error(
            status.HTTP_409_CONFLICT,
            ANALYSIS_FAILED_CODE,
            job.error_message or ANALYSIS_FAILED_FALLBACK_MESSAGE,
        )
    if job.status == JobStatus.EXPIRED or job.expires_at <= datetime.now(UTC):
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


def _require_version(
    job_id: UUID,
    version_id: UUID,
    repository: RevisionRepository,
) -> None:
    version = repository.get_version(version_id)
    if version is None or version.job_id != job_id:
        raise _http_error(
            status.HTTP_404_NOT_FOUND,
            VERSION_NOT_FOUND_CODE,
            VERSION_NOT_FOUND_MESSAGE,
        )


def _require_succeeded_version(
    job_id: UUID,
    version_id: UUID,
    repository: RevisionRepository,
) -> DocumentVersionRead:
    version = repository.get_version(version_id)
    if version is None or version.job_id != job_id:
        raise _http_error(
            status.HTTP_404_NOT_FOUND,
            VERSION_NOT_FOUND_CODE,
            VERSION_NOT_FOUND_MESSAGE,
        )
    if version.status != DocumentVersionStatus.SUCCEEDED:
        raise _http_error(
            status.HTTP_409_CONFLICT,
            ANALYSIS_NOT_READY_CODE,
            "分析结果尚未就绪，请稍后重试。",
        )
    return version


def _draft_conflict(current_revision: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": STALE_DRAFT_REVISION_CODE,
            "message": "草稿已更新，请刷新后重试。",
            "current_revision": current_revision,
        },
    )


def _draft_consumed_conflict() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "draft_consumed",
            "message": "草稿已被消费，请刷新后重试。",
        },
    )


def _invalid_draft_blocks(error: InvalidDraftBlocksError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={
            "code": INVALID_DRAFT_BLOCKS_CODE,
            "message": "草稿段落列表无效，请刷新后重试。",
            "duplicate_block_ids": list(error.duplicate_block_ids),
            "missing_block_ids": list(error.missing_block_ids),
            "unexpected_block_ids": list(error.unexpected_block_ids),
        },
    )


def _derived_content_conflict(error: DerivedContentValidationError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": error.code,
            "message": _derived_content_error_message(error.code),
            "issue_ids": [str(issue_id) for issue_id in error.issue_ids],
        },
    )


def _derived_content_error_message(code: str) -> str:
    if code == "overlapping_replacements":
        return "已接受的修改范围存在冲突，请先保留其中一个后重试。"
    return "无法生成修改后内容，请刷新问题处理状态后重试。"


def dispatch_process_document_version(version_id: str) -> None:
    worker_tasks = import_module("text_verification.workers.reanalysis_tasks")
    process_document_version = worker_tasks.process_document_version
    process_document_version.delay(version_id)


def _recover_from_reanalysis_dispatch_failure(
    session: Session,
    revision_repository: RevisionRepository,
    version_id: UUID,
) -> None:
    last_error: Exception | None = None
    for _ in range(DISPATCH_RECOVERY_MAX_ATTEMPTS):
        try:
            version = revision_repository.get_version(version_id)
            if version is None or version.status in {
                DocumentVersionStatus.SUCCEEDED,
                DocumentVersionStatus.FAILED,
            }:
                return
            revision_repository.fail_version(
                version_id,
                code="reanalysis_dispatch_failed",
                message="重新分析调度失败，请稍后重试。",
            )
            session.commit()
            return
        except Exception as persist_error:
            last_error = persist_error
            session.rollback()
    raise ReanalysisDispatchRecoveryError(
        f"Failed to persist dispatch failure for document version {version_id}."
    ) from last_error


async def _version_event_stream(
    version_id: UUID,
    after_sequence: int,
    request: Request,
) -> AsyncIterator[str]:
    session_factory = SESSION_FACTORY_PROVIDER()
    last_keepalive = monotonic()

    while True:
        if await request.is_disconnected():
            return

        events, version, job_expired = _poll_version_state(
            session_factory,
            version_id,
            after_sequence,
        )
        emitted = False
        for event in events:
            yield _format_version_event(event)
            after_sequence = event.sequence
            last_keepalive = monotonic()
            emitted = True

        if version is None or job_expired:
            yield _format_control_event("expired")
            return

        if version.status in {
            DocumentVersionStatus.SUCCEEDED,
            DocumentVersionStatus.FAILED,
        }:
            yield _format_control_event("done")
            return

        if not emitted and monotonic() - last_keepalive >= SSE_KEEPALIVE_SECONDS:
            yield ": keepalive\n\n"
            last_keepalive = monotonic()

        await asyncio.sleep(SSE_POLL_SECONDS)


def _poll_version_state(
    session_factory: sessionmaker[Session],
    version_id: UUID,
    after_sequence: int,
) -> tuple[list[DocumentVersionEvent], DocumentVersionRead | None, bool]:
    session = session_factory()
    try:
        repository = REVISION_REPOSITORY_FACTORY(session)
        version = repository.get_version(version_id)
        events = repository.list_version_events_after(version_id, after_sequence)
        if version is None:
            return events, None, True
        job = JobRepository(session).get_job(version.job_id)
        job_expired = (
            job is None
            or job.status == JobStatus.EXPIRED
            or job.expires_at <= datetime.now(UTC)
        )
        return events, version, job_expired
    finally:
        session.close()


def _format_version_event(event: DocumentVersionEvent) -> str:
    payload_data: dict[str, object] = {
        "status": event.status.value,
        "progress": event.progress,
        "message": event.message,
        "created_at": event.created_at.isoformat(),
    }
    if event.metadata is not None:
        payload_data.update(event.metadata.model_dump(mode="json"))
    payload = json.dumps(
        payload_data,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"id: {event.sequence}\nevent: progress\ndata: {payload}\n\n"
