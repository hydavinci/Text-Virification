from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from text_verification.checkers.models import CheckCategory

HEX_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class DocumentVersionStatus(StrEnum):
    QUEUED = "queued"
    ANALYZING = "analyzing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ImmutableDocumentVersionError(ValueError):
    def __init__(self, version_id: UUID, status: DocumentVersionStatus) -> None:
        self.version_id = version_id
        self.status = status
        super().__init__(
            f"Document version {version_id} is immutable after reaching {status.value}."
        )


class DraftBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_id: str = Field(min_length=1, max_length=64)
    text: str = Field(max_length=1_000_000)


class DocumentVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version_id: UUID
    job_id: UUID
    parent_version_id: UUID | None = None
    revision_number: int = Field(ge=1)
    status: DocumentVersionStatus
    source_kind: str = Field(min_length=1, max_length=32)
    created_reason: str = Field(min_length=1, max_length=32)
    content_sha256: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failure_code: str | None = None
    failure_message: str | None = None

    @model_validator(mode="after")
    def validate_state(self) -> DocumentVersionRead:
        if self.content_sha256 is not None and HEX_SHA256_PATTERN.fullmatch(
            self.content_sha256
        ) is None:
            raise ValueError("content_sha256 must be a lowercase SHA-256 hex digest")
        if self.status == DocumentVersionStatus.FAILED:
            if self.failure_code is None or self.failure_message is None:
                raise ValueError("failed versions must include failure details")
            return self
        if self.failure_code is not None or self.failure_message is not None:
            raise ValueError("non-failed versions must not include failure details")
        return self


class EditDraftRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    draft_id: UUID
    job_id: UUID
    base_version_id: UUID
    revision: int = Field(ge=1)
    blocks: list[DraftBlock]
    content_sha256: str | None = None
    created_at: datetime
    updated_at: datetime
    consumed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_blocks(self) -> EditDraftRead:
        if self.content_sha256 is not None and HEX_SHA256_PATTERN.fullmatch(
            self.content_sha256
        ) is None:
            raise ValueError("content_sha256 must be a lowercase SHA-256 hex digest")
        block_ids = [block.block_id for block in self.blocks]
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("draft blocks must not contain duplicate block_id values")
        return self


class DocumentVersionEventMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_category: CheckCategory
    completed_categories: list[CheckCategory]
    issue_count: int = Field(ge=0)


@dataclass(frozen=True)
class DocumentVersionEvent:
    sequence: int
    status: DocumentVersionStatus
    progress: int
    message: str
    created_at: datetime
    metadata: DocumentVersionEventMetadata | None = None
