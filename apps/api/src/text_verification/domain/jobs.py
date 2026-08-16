from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from text_verification.checkers.models import CHECK_CATEGORY_ORDER, CheckCategory, CheckScenario
from text_verification.domain.documents import FileType


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


class TerminalJobStateError(RuntimeError):
    def __init__(
        self,
        *,
        job_id: UUID,
        current_status: JobStatus,
        target_status: JobStatus,
    ) -> None:
        self.job_id = job_id
        self.current_status = current_status
        self.target_status = target_status
        super().__init__(
            "Job "
            f"{job_id} is already terminal ({current_status.value}); "
            f"refusing transition to {target_status.value}."
        )


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: UUID
    source_name: str
    file_type: FileType
    size_bytes: int
    status: JobStatus
    progress: int
    error_code: str | None = None
    error_message: str | None = None
    scenario: CheckScenario = CheckScenario.GENERAL
    enabled_categories: list[CheckCategory] = Field(
        default_factory=lambda: list(CHECK_CATEGORY_ORDER)
    )
    created_at: datetime
    expires_at: datetime

    @field_validator("scenario", mode="before")
    @classmethod
    def default_scenario(cls, value: object) -> object:
        return CheckScenario.GENERAL if value is None else value

    @field_validator("enabled_categories", mode="before")
    @classmethod
    def default_enabled_categories(cls, value: object) -> object:
        return list(CHECK_CATEGORY_ORDER) if value is None else value


@dataclass(frozen=True)
class JobEvent:
    sequence: int
    status: JobStatus
    progress: int
    message: str
    created_at: datetime
