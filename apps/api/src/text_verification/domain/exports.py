from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SUPPORTED_EXPORT_EXTENSIONS = frozenset({"txt", "docx", "html", "pdf"})


class ExportType(StrEnum):
    MODIFIED_DOCUMENT = "modified_document"
    HTML_REPORT = "html_report"
    PDF_REPORT = "pdf_report"


class ExportStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


TERMINAL_EXPORT_STATUSES = {
    ExportStatus.COMPLETED,
    ExportStatus.FAILED,
}


def normalize_export_extension(value: str) -> str:
    normalized = value.lower()
    if normalized not in SUPPORTED_EXPORT_EXTENSIONS:
        raise ValueError(f"Unsupported export extension: {value}")
    return normalized


def validate_export_file_name(value: str) -> str:
    if not value:
        raise ValueError("file_name must not be empty")
    if any(separator in value for separator in ("/", "\\")) or value in {".", ".."}:
        raise ValueError("file_name must be a server-controlled basename")
    suffix = Path(value).suffix.removeprefix(".")
    normalize_export_extension(suffix)
    return value


class TerminalExportStateError(RuntimeError):
    def __init__(
        self,
        *,
        export_id: UUID,
        current_status: ExportStatus,
        target_status: ExportStatus,
    ) -> None:
        self.export_id = export_id
        self.current_status = current_status
        self.target_status = target_status
        super().__init__(
            "Export "
            f"{export_id} is already terminal ({current_status.value}); "
            f"refusing transition to {target_status.value}."
        )


class ExportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    export_id: UUID
    job_id: UUID
    export_type: ExportType
    status: ExportStatus
    file_name: str = Field(min_length=1, max_length=255)
    storage_key: str = Field(min_length=1, max_length=255)
    warnings: list[str] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime

    @field_validator("file_name")
    @classmethod
    def normalize_file_name(cls, value: str) -> str:
        return validate_export_file_name(value)

    @model_validator(mode="after")
    def validate_state(self) -> ExportRead:
        if self.status == ExportStatus.FAILED:
            if self.error_code is None or self.error_message is None:
                raise ValueError("failed exports must include error details")
            return self
        if self.error_code is not None or self.error_message is not None:
            raise ValueError("non-failed exports must not include error details")
        return self
