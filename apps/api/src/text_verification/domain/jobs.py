from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, computed_field

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


class JobProgressStage(StrEnum):
    QUEUED = "queued"
    UPLOAD_VALIDATED = "upload_validated"
    PARSING = "parsing"
    OCR = "ocr"
    CHECKING_FORMAT = "checking_format"
    CHECKING_SENSITIVE = "checking_sensitive"
    CHECKING_CHINESE = "checking_chinese"
    CHECKING_ENGLISH = "checking_english"
    EXPORTING = "exporting"
    FINALIZING = "finalizing"
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

RESULT_READY_STATUSES = {
    JobStatus.COMPLETED,
    JobStatus.PARTIAL,
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


class JobLeaseLostError(RuntimeError):
    def __init__(
        self,
        job_id: UUID,
        lease_expires_at: datetime,
    ) -> None:
        self.job_id = job_id
        self.lease_expires_at = lease_expires_at
        super().__init__(f"Job {job_id} is not owned by the active processing lease.")


class JobUnleasedError(RuntimeError):
    def __init__(self, job_id: UUID) -> None:
        self.job_id = job_id
        super().__init__(f"Job {job_id} has no active processing lease.")


class JobStateConflictError(RuntimeError):
    def __init__(
        self,
        *,
        job_id: UUID,
        expected_status: JobStatus,
        current_status: JobStatus,
    ) -> None:
        self.job_id = job_id
        self.expected_status = expected_status
        self.current_status = current_status
        super().__init__(
            f"Job {job_id} expected status {expected_status.value}, "
            f"found {current_status.value}."
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
    error_stage: str | None = None
    error_retryable: bool | None = None
    created_at: datetime
    expires_at: datetime

    @computed_field
    def stage(self) -> JobProgressStage:
        return _stage_from_status_progress(self.status, self.progress)


@dataclass(frozen=True, init=False)
class JobEvent:
    sequence: int
    status: JobStatus
    stage: JobProgressStage
    progress: int
    message: str
    created_at: datetime

    def __init__(
        self,
        sequence: int,
        status: JobStatus,
        progress: int,
        message: str,
        created_at: datetime,
        stage: JobProgressStage | None = None,
    ) -> None:
        object.__setattr__(self, "sequence", sequence)
        object.__setattr__(self, "status", status)
        object.__setattr__(
            self,
            "stage",
            stage or _stage_from_persisted_event(status, progress, message),
        )
        object.__setattr__(self, "progress", progress)
        object.__setattr__(self, "message", message)
        object.__setattr__(self, "created_at", created_at)


def _stage_from_persisted_event(
    status: JobStatus,
    progress: int,
    message: str,
) -> JobProgressStage:
    special_stage = {
        "正在重建文档": JobProgressStage.EXPORTING,
        "正在保存导出文件": JobProgressStage.FINALIZING,
    }.get(message)
    return special_stage or _stage_from_status_progress(status, progress)


def _stage_from_status_progress(
    status: JobStatus,
    progress: int,
) -> JobProgressStage:
    if status is JobStatus.PARSING and progress >= 40:
        return JobProgressStage.OCR
    if status is JobStatus.CHECKING_ENGLISH and progress >= 95:
        return JobProgressStage.FINALIZING
    return JobProgressStage(status.value)


class JobClaimDisposition(StrEnum):
    ACQUIRED = "acquired"
    MISSING = "missing"
    TERMINAL = "terminal"
    LEASED = "leased"
    RETENTION_EXPIRED = "retention_expired"


@dataclass(frozen=True)
class JobClaimResult:
    disposition: JobClaimDisposition
    job: JobRead | None
    lease_expires_at: datetime | None = None


class JobRecoveryKind(StrEnum):
    INITIAL_DISPATCH = "initial_dispatch"
    EXPIRED_LEASE = "expired_lease"


@dataclass(frozen=True)
class JobRecoveryClaim:
    kind: JobRecoveryKind
    job: JobRead
    attempt: int
    publication_due_at: datetime
