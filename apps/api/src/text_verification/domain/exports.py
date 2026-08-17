from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
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

SUPPORTED_EXPORT_TYPE_EXTENSIONS: dict[ExportType, frozenset[str]] = {
    ExportType.MODIFIED_DOCUMENT: frozenset({"txt", "docx"}),
    ExportType.HTML_REPORT: frozenset({"html"}),
    ExportType.PDF_REPORT: frozenset({"pdf"}),
}

EXPORT_FILE_STEMS: dict[ExportType, str] = {
    ExportType.MODIFIED_DOCUMENT: "modified_document",
    ExportType.HTML_REPORT: "report",
    ExportType.PDF_REPORT: "report",
}


@dataclass(frozen=True)
class ExportArtifact:
    file_name: str
    storage_name: str
    storage_key: str


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
    extension = Path(value).suffix.removeprefix(".")
    if not extension:
        raise ValueError("file_name must include a supported extension")
    normalize_export_extension(extension)
    return value


def build_export_storage_name(export_id: UUID, extension: str) -> str:
    return f"{export_id}.{normalize_export_extension(extension)}"


def build_export_storage_key(job_id: UUID, export_id: UUID, extension: str) -> str:
    return str(PurePosixPath(str(job_id)) / build_export_storage_name(export_id, extension))


def build_export_artifact(
    *,
    job_id: UUID,
    export_id: UUID,
    export_type: ExportType | str,
    extension: str,
) -> ExportArtifact:
    normalized_type = (
        export_type if isinstance(export_type, ExportType) else ExportType(export_type)
    )
    normalized_extension = normalize_export_extension(extension)
    supported_extensions = SUPPORTED_EXPORT_TYPE_EXTENSIONS[normalized_type]
    if normalized_extension not in supported_extensions:
        supported_list = ", ".join(sorted(supported_extensions))
        raise ValueError(
            f"Export type {normalized_type.value} only supports extension {supported_list}"
        )

    file_name = f"{EXPORT_FILE_STEMS[normalized_type]}.{normalized_extension}"
    storage_name = build_export_storage_name(export_id, normalized_extension)
    return ExportArtifact(
        file_name=file_name,
        storage_name=storage_name,
        storage_key=build_export_storage_key(job_id, export_id, normalized_extension),
    )


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
        file_name_extension = Path(self.file_name).suffix.removeprefix(".")
        expected_artifact = build_export_artifact(
            job_id=self.job_id,
            export_id=self.export_id,
            export_type=self.export_type,
            extension=file_name_extension,
        )
        if self.file_name != expected_artifact.file_name:
            raise ValueError("export file_name must use the server-generated value")
        if self.storage_key != expected_artifact.storage_key:
            raise ValueError("export storage_key must use the server-generated value")
        if self.status == ExportStatus.FAILED:
            if self.error_code is None or self.error_message is None:
                raise ValueError("failed exports must include error details")
            return self
        if self.error_code is not None or self.error_message is not None:
            raise ValueError("non-failed exports must not include error details")
        return self
