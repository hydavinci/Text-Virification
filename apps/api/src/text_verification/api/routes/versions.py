from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from text_verification.api.dependencies import (
    get_db_session,
    get_job_repository,
    get_revision_repository,
)
from text_verification.api.routes.jobs import JOB_NOT_FOUND_CODE, _http_error
from text_verification.domain.revisions import DocumentVersionRead, DraftBlock, EditDraftRead
from text_verification.infrastructure.repositories import JobRepository
from text_verification.infrastructure.revision_repository import (
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

router = APIRouter(tags=["versions"])


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
    except Exception:
        session.rollback()
        raise
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _lock_job(job_id: UUID, repository: JobRepository) -> None:
    try:
        repository.lock_job(job_id)
    except LookupError as error:
        raise _http_error(
            status.HTTP_404_NOT_FOUND,
            JOB_NOT_FOUND_CODE,
            "作业不存在。",
        ) from error


def _require_job(job_id: UUID, repository: JobRepository) -> None:
    if repository.get_job(job_id) is None:
        raise _http_error(
            status.HTTP_404_NOT_FOUND,
            JOB_NOT_FOUND_CODE,
            "作业不存在。",
        )


def _draft_conflict(current_revision: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": STALE_DRAFT_REVISION_CODE,
            "message": "草稿已更新，请刷新后重试。",
            "current_revision": current_revision,
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
