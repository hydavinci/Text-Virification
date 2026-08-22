from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from text_verification.api.dependencies import (
    get_db_session,
    get_job_repository,
    get_revision_repository,
)
from text_verification.api.routes.analysis import (
    _require_job,
    _require_version,
)
from text_verification.api.routes.jobs import _http_error
from text_verification.domain.review_operations import ReviewOperationBatchRead
from text_verification.infrastructure.repositories import JobRepository
from text_verification.infrastructure.review_operation_repository import (
    OperationBatchNotFound,
    OperationUndoConflict,
    ReviewOperationRepository,
)
from text_verification.infrastructure.revision_repository import RevisionRepository

OPERATION_BATCH_NOT_FOUND_CODE = "operation_batch_not_found"
OPERATION_UNDO_CONFLICT_CODE = "operation_undo_conflict"

router = APIRouter(tags=["review-history"])


class ReviewOperationPageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    version_id: UUID
    total: int
    items: list[ReviewOperationBatchRead]
    next_cursor: None = None


@router.get(
    "/jobs/{job_id}/operation-batches",
    response_model=ReviewOperationPageResponse,
)
def list_operation_batches(
    job_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    job_repository: Annotated[JobRepository, Depends(get_job_repository)],
    revision_repository: Annotated[RevisionRepository, Depends(get_revision_repository)],
    version_id: UUID | None = None,
) -> ReviewOperationPageResponse:
    _require_job(job_id, job_repository)
    resolved_version_id = _require_version(job_id, version_id, revision_repository)
    page = ReviewOperationRepository(session).list_batches(
        job_id,
        version_id=resolved_version_id,
    )
    return ReviewOperationPageResponse(
        job_id=page.job_id,
        version_id=page.version_id,
        total=page.total,
        items=page.items,
        next_cursor=page.next_cursor,
    )


@router.post(
    "/jobs/{job_id}/operation-batches/{batch_id}/undo",
    response_model=ReviewOperationBatchRead,
)
def undo_operation_batch(
    job_id: UUID,
    batch_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    job_repository: Annotated[JobRepository, Depends(get_job_repository)],
) -> ReviewOperationBatchRead:
    _require_job(job_id, job_repository)
    try:
        result = ReviewOperationRepository(session).undo(job_id, batch_id)
        session.commit()
    except OperationBatchNotFound as error:
        session.rollback()
        raise _http_error(
            status.HTTP_404_NOT_FOUND,
            OPERATION_BATCH_NOT_FOUND_CODE,
            "操作批次不存在。",
        ) from error
    except OperationUndoConflict as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": OPERATION_UNDO_CONFLICT_CODE,
                "message": "问题决策已在该操作后发生变化，无法撤销。",
                "issue_ids": [str(issue_id) for issue_id in error.issue_ids],
            },
        ) from error
    except Exception:
        session.rollback()
        raise
    return result
