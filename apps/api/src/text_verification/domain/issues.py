import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from text_verification.domain.review_operations import IssueSuggestion


class IssueSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class DecisionAction(StrEnum):
    ACCEPTED = "accepted"
    IGNORED = "ignored"
    UNREVIEWED = "unreviewed"


NON_WHITESPACE_PATTERN = re.compile(r"\S")
MAX_CUSTOM_REPLACEMENT_CODE_POINTS = 10_000


def _reject_nul(value: str) -> str:
    if "\0" in value:
        raise ValueError("replacement must not contain NUL")
    return value


CustomReplacement = Annotated[
    str,
    Field(max_length=MAX_CUSTOM_REPLACEMENT_CODE_POINTS),
    AfterValidator(_reject_nul),
]


class IssueDecisionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_version: int = Field(gt=0)
    revision: int = Field(default=0, ge=0)
    action: DecisionAction
    replacement: CustomReplacement | None = None
    suggestion_id: UUID | None = None
    updated_at: datetime

    @model_validator(mode="after")
    def validate_replacement(self) -> "IssueDecisionSummary":
        if self.action == DecisionAction.ACCEPTED:
            if (
                self.replacement is None
                or NON_WHITESPACE_PATTERN.search(self.replacement) is None
            ):
                raise ValueError("accepted decisions require a non-empty replacement")
            return self
        if self.action == DecisionAction.UNREVIEWED:
            raise ValueError("unreviewed is a command-only decision state")
        if self.replacement is not None or self.suggestion_id is not None:
            raise ValueError("ignored decisions must not include replacement details")
        return self


class Issue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_id: UUID
    document_id: UUID
    document_version: int | None = Field(default=None, gt=0)
    block_id: str
    page: int | None
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    original: str
    suggestion: str | None
    alternatives: list[str]
    suggestions: list[IssueSuggestion] = Field(default_factory=list)
    type: str
    severity: IssueSeverity
    layer: str
    message: str
    rule_id: str
    source: str
    source_version: str
    confidence: float = Field(ge=0, le=1)
    auto_fixable: bool
    context: str
    decision: IssueDecisionSummary | None = None

    @model_validator(mode="after")
    def validate_range(self) -> "Issue":
        if self.end <= self.start:
            raise ValueError("end must be greater than start")
        return self


class DecisionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_id: UUID
    issue_version: int = Field(gt=0)
    expected_revision: int = Field(ge=0)
    action: DecisionAction
    replacement: CustomReplacement | None = None
    suggestion_id: UUID | None = None

    @model_validator(mode="after")
    def validate_replacement(self) -> "DecisionCommand":
        if self.action == DecisionAction.ACCEPTED:
            if (
                self.replacement is None
                or NON_WHITESPACE_PATTERN.search(self.replacement) is None
            ):
                raise ValueError("accepted decisions require a non-empty replacement")
            return self
        if self.replacement is not None or self.suggestion_id is not None:
            raise ValueError(
                f"{self.action.value} decisions must not include replacement details"
            )
        return self


class IssueDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_id: UUID
    issue_version: int = Field(gt=0)
    revision: int = Field(default=0, ge=0)
    action: DecisionAction
    replacement: CustomReplacement | None = None
    suggestion_id: UUID | None = None
    updated_at: datetime

    @model_validator(mode="after")
    def validate_replacement(self) -> "IssueDecision":
        if self.action == DecisionAction.ACCEPTED:
            if (
                self.replacement is None
                or NON_WHITESPACE_PATTERN.search(self.replacement) is None
            ):
                raise ValueError("accepted decisions require a non-empty replacement")
            return self
        if self.action == DecisionAction.UNREVIEWED:
            raise ValueError("unreviewed is a command-only decision state")
        if self.replacement is not None or self.suggestion_id is not None:
            raise ValueError("ignored decisions must not include replacement details")
        return self
