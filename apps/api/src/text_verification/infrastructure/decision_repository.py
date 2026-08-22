from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy.orm import Session

from text_verification.domain.issues import DecisionAction, DecisionCommand, IssueDecision
from text_verification.infrastructure.review_operation_repository import (
    DecisionBatchConflict,
    ReviewOperationRepository,
)

ISSUE_NOT_FOUND_CODE = "issue_not_found"
STALE_ISSUE_VERSION_CODE = "stale_issue_version"
UNSUPPORTED_DECISION_ACTION_CODE = "unsupported_decision_action"


class DecisionOutcomeStatus(StrEnum):
    APPLIED = "applied"
    CONFLICT = "conflict"
    INVALID = "invalid"


class DecisionOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_id: UUID
    status: DecisionOutcomeStatus
    code: str | None = None
    decision: IssueDecision | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> DecisionOutcome:
        if self.status == DecisionOutcomeStatus.APPLIED:
            if self.code is not None:
                raise ValueError("applied outcomes must not include a code")
            return self
        if self.code is None:
            raise ValueError("non-applied outcomes must include a code")
        if self.decision is not None:
            raise ValueError("non-applied outcomes must not include a decision")
        return self


class DecisionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def apply(self, job_id: UUID, command: DecisionCommand) -> DecisionOutcome:
        try:
            result = ReviewOperationRepository(self._session).apply_decisions(
                job_id,
                [command],
            )
        except DecisionBatchConflict as error:
            code = error.conflicts[command.issue_id]
            return DecisionOutcome(
                issue_id=command.issue_id,
                status=(
                    DecisionOutcomeStatus.CONFLICT
                    if code.startswith("stale_")
                    else DecisionOutcomeStatus.INVALID
                ),
                code=code,
            )

        item = result.items[0]
        return DecisionOutcome(
            issue_id=command.issue_id,
            status=DecisionOutcomeStatus.APPLIED,
            decision=(
                None
                if item.after is None
                else _snapshot_to_decision(
                    command.issue_id,
                    item.after,
                    updated_at=item.updated_at,
                )
            ),
        )


def _snapshot_to_decision(
    issue_id: UUID,
    snapshot: dict[str, object],
    *,
    updated_at: datetime,
) -> IssueDecision:
    return IssueDecision(
        issue_id=issue_id,
        issue_version=_required_int(snapshot["issue_version"]),
        revision=_required_int(snapshot["revision"]),
        action=DecisionAction(str(snapshot["action"])),
        replacement=(
            None
            if snapshot["final_replacement"] is None
            else str(snapshot["final_replacement"])
        ),
        suggestion_id=(
            None if snapshot["suggestion_id"] is None else UUID(str(snapshot["suggestion_id"]))
        ),
        updated_at=updated_at,
    )


def _required_int(value: object) -> int:
    if not isinstance(value, int):
        raise TypeError("decision snapshot integer field is invalid")
    return value
