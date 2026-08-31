from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class IssueSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Issue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_id: UUID
    document_id: UUID
    verification_run_id: UUID
    block_id: str | None
    page: int | None
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    block_start: int | None = Field(default=None, ge=0)
    block_end: int | None = Field(default=None, gt=0)
    original: str
    suggestion: str | None
    alternatives: list[str]
    type: str
    severity: IssueSeverity
    layer: str
    message: str
    description: str
    rule_id: str
    rule_version: str
    source: str
    source_version: str
    confidence: float = Field(ge=0, le=1)
    auto_fixable: bool
    context: str
    review: str | None = None
    review_reason: str | None = None

    @model_validator(mode="after")
    def validate_range(self) -> "Issue":
        if self.end <= self.start:
            raise ValueError("end must be greater than start")
        if (self.block_start is None) != (self.block_end is None):
            raise ValueError("block_start and block_end must be provided together")
        if (
            self.block_start is not None
            and self.block_end is not None
            and self.block_end <= self.block_start
        ):
            raise ValueError("block_end must be greater than block_start")
        if len(self.original) != self.end - self.start:
            raise ValueError("original text length must match the global issue range")
        if self.block_id is None and self.block_start is not None:
            raise ValueError("block offsets require a block_id")
        if self.block_id is not None and self.block_start is None:
            raise ValueError("block_id requires block_start and block_end")
        if (
            self.block_start is not None
            and self.block_end is not None
            and self.block_end - self.block_start != self.end - self.start
        ):
            raise ValueError("block range length must match the global issue range")
        return self
