from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from text_verification.api.dependencies import (
    get_analysis_repository,
    get_db_session,
    get_job_repository,
)
from text_verification.api.routes.analysis import (
    ANALYSIS_NOT_READY_CODE,
    _require_analysis,
    _require_ready_job,
)
from text_verification.api.routes.jobs import _http_error
from text_verification.domain.issues import DecisionCommand
from text_verification.infrastructure.analysis_repositories import AnalysisRepository
from text_verification.infrastructure.decision_repository import (
    DecisionOutcome,
)
from text_verification.infrastructure.repositories import JobRepository
from text_verification.infrastructure.review_operation_repository import (
    DecisionBatchConflict,
    OverlappingDecisions,
    ReviewOperationRepository,
)

DECISION_BATCH_CONFLICT_CODE = "decision_batch_conflict"
DUPLICATE_ISSUE_DECISION_CODE = "duplicate_issue_decision"
MAX_DECISIONS_PER_BATCH = 500
OVERLAPPING_DECISIONS_CODE = "overlapping_decisions"

router = APIRouter(tags=["decisions"])


class DecisionBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[DecisionCommand] = Field(min_length=1, max_length=MAX_DECISIONS_PER_BATCH)


class DecisionBatchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: UUID
    outcomes: list[DecisionOutcome]


@router.put("/jobs/{job_id}/decisions", response_model=DecisionBatchResponse)
def put_decisions(
    job_id: UUID,
    payload: DecisionBatchRequest,
    session: Annotated[Session, Depends(get_db_session)],
    job_repository: Annotated[JobRepository, Depends(get_job_repository)],
    analysis_repository: Annotated[AnalysisRepository, Depends(get_analysis_repository)],
) -> DecisionBatchResponse:
    _ensure_unique_issue_ids(payload.decisions)
    _require_ready_job(job_id, job_repository)
    _require_analysis(
        job_id,
        analysis_repository,
        missing_status_code=status.HTTP_409_CONFLICT,
        missing_code=ANALYSIS_NOT_READY_CODE,
        missing_message="分析结果尚未就绪，请稍后重试。",
    )

    repository = ReviewOperationRepository(session)
    try:
        result = repository.apply_decisions(job_id, payload.decisions)
        session.commit()
    except DecisionBatchConflict as error:
        session.rollback()
        raise _http_error_with_issue_ids(
            status.HTTP_409_CONFLICT,
            DECISION_BATCH_CONFLICT_CODE,
            "问题决策已过期或无效，请刷新后重试。",
            sorted(error.conflicts),
        ) from error
    except OverlappingDecisions as error:
        session.rollback()
        raise _http_error_with_issue_ids(
            status.HTTP_409_CONFLICT,
            OVERLAPPING_DECISIONS_CODE,
            "接受的修改范围相互重叠，请仅保留其中一个。",
            error.issue_ids,
        ) from error
    except Exception:
        session.rollback()
        raise

    outcomes = [
        DecisionOutcome(
            issue_id=item.command.issue_id,
            status="applied",
            decision=(
                None
                if item.after is None
                else {
                    "issue_id": item.command.issue_id,
                    "issue_version": item.after["issue_version"],
                    "revision": item.after["revision"],
                    "action": item.after["action"],
                    "replacement": item.after["final_replacement"],
                    "suggestion_id": item.after["suggestion_id"],
                    "updated_at": item.updated_at,
                }
            ),
        )
        for item in result.items
    ]
    return DecisionBatchResponse(batch_id=result.batch.batch_id, outcomes=outcomes)


def _ensure_unique_issue_ids(decisions: list[DecisionCommand]) -> None:
    seen: set[UUID] = set()
    for command in decisions:
        if command.issue_id in seen:
            raise _http_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                DUPLICATE_ISSUE_DECISION_CODE,
                "同一请求中不能重复提交同一问题的决策。",
            )
        seen.add(command.issue_id)


def _http_error_with_issue_ids(
    status_code: int,
    code: str,
    message: str,
    issue_ids: list[UUID],
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
            "issue_ids": [str(issue_id) for issue_id in issue_ids],
        },
    )
