from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SuggestionSource(StrEnum):
    RULE = "rule"
    DICTIONARY = "dictionary"
    LLM = "llm"
    MANUAL = "manual"


class IssueSuggestion(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    suggestion_id: UUID
    text: str = Field(min_length=1)
    source: SuggestionSource
    explanation: str | None = None
    rank: int = Field(ge=0)
    preferred: bool


class ReviewOperationType(StrEnum):
    DECISION = "decision"
    UNDO = "undo"


class ReviewOperationBatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    batch_id: UUID
    job_id: UUID
    version_id: UUID
    operation_type: ReviewOperationType
    affected_count: int = Field(ge=0)
    undoes_batch_id: UUID | None = None
    created_at: datetime
