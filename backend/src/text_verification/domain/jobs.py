from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class JobStatus(StrEnum):
    QUEUED = "queued"
    UPLOAD_VALIDATED = "upload_validated"
    PARSING = "parsing"
    CHECKING_FORMAT = "checking_format"
    CHECKING_SENSITIVE = "checking_sensitive"
    CHECKING_CHINESE = "checking_chinese"
    CHECKING_ENGLISH = "checking_english"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    EXPIRED = "expired"


TERMINAL_STATUSES = {
    JobStatus.COMPLETED,
    JobStatus.PARTIAL,
    JobStatus.FAILED,
    JobStatus.EXPIRED,
}


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: UUID
    source_name: str
    file_type: str
    size_bytes: int
    status: JobStatus
    progress: int
    error_code: str | None
    error_message: str | None
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class JobEvent:
    sequence: int
    status: JobStatus
    progress: int
    message: str
    created_at: datetime
