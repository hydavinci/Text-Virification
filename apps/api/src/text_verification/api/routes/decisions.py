from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
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
    DecisionRepository,
)
from text_verification.infrastructure.repositories import JobRepository

DUPLICATE_ISSUE_DECISION_CODE = "duplicate_issue_decision"
MAX_DECISIONS_PER_BATCH = 500

router = APIRouter(tags=["decisions"])


class DecisionBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[DecisionCommand] = Field(min_length=1, max_length=MAX_DECISIONS_PER_BATCH)


class DecisionBatchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

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

    job_repository.lock_job(job_id)
    repository = DecisionRepository(session)
    outcomes: list[DecisionOutcome] = []
    try:
        for command in payload.decisions:
            with session.begin_nested():
                outcomes.append(repository.apply(job_id, command))
        session.commit()
    except Exception:
        session.rollback()
        raise

    return DecisionBatchResponse(outcomes=outcomes)


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
