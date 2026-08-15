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
    block_id: str
    page: int | None
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    original: str
    suggestion: str | None
    alternatives: list[str]
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

    @model_validator(mode="after")
    def validate_range(self) -> "Issue":
        if self.end <= self.start:
            raise ValueError("end must be greater than start")
        return self
