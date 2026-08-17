from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from text_verification.domain.issues import DecisionAction, DecisionCommand, IssueDecision
from text_verification.infrastructure.orm import IssueDecisionRow, IssueRow

ISSUE_NOT_FOUND_CODE = "issue_not_found"
STALE_ISSUE_VERSION_CODE = "stale_issue_version"


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
            if self.decision is None:
                raise ValueError("applied outcomes must include a decision")
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
        issue_row = self._session.execute(
            select(IssueRow)
            .where(
                IssueRow.job_id == job_id,
                IssueRow.issue_id == command.issue_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if issue_row is None:
            return DecisionOutcome(
                issue_id=command.issue_id,
                status=DecisionOutcomeStatus.INVALID,
                code=ISSUE_NOT_FOUND_CODE,
            )
        if issue_row.document_version != command.issue_version:
            return DecisionOutcome(
                issue_id=command.issue_id,
                status=DecisionOutcomeStatus.CONFLICT,
                code=STALE_ISSUE_VERSION_CODE,
            )

        decision_row = self._session.execute(
            select(IssueDecisionRow)
            .where(IssueDecisionRow.issue_id == command.issue_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if decision_row is not None and _matches_command(decision_row, command):
            return DecisionOutcome(
                issue_id=command.issue_id,
                status=DecisionOutcomeStatus.APPLIED,
                decision=_to_issue_decision(decision_row),
            )

        updated_at = datetime.now(UTC)
        if decision_row is None:
            decision_row = IssueDecisionRow(
                issue_id=command.issue_id,
                job_id=job_id,
                issue_version=command.issue_version,
                action=command.action.value,
                replacement=command.replacement,
                updated_at=updated_at,
            )
            self._session.add(decision_row)
        else:
            decision_row.job_id = job_id
            decision_row.issue_version = command.issue_version
            decision_row.action = command.action.value
            decision_row.replacement = command.replacement
            decision_row.updated_at = updated_at

        self._session.flush()

        return DecisionOutcome(
            issue_id=command.issue_id,
            status=DecisionOutcomeStatus.APPLIED,
            decision=_to_issue_decision(decision_row),
        )


def _matches_command(row: IssueDecisionRow, command: DecisionCommand) -> bool:
    return (
        row.issue_version == command.issue_version
        and row.action == command.action.value
        and row.replacement == command.replacement
    )


def _to_issue_decision(row: IssueDecisionRow) -> IssueDecision:
    return IssueDecision(
        issue_id=row.issue_id,
        issue_version=row.issue_version,
        action=DecisionAction(row.action),
        replacement=row.replacement,
        updated_at=row.updated_at,
    )
