from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from text_verification.checkers.models import CheckCategory, CheckScenario
from text_verification.domain.documents import DocumentModel, FileType
from text_verification.domain.issues import (
    DecisionAction,
    Issue,
    IssueDecisionSummary,
    IssueSeverity,
)

SUPPORTED_EXPORT_EXTENSIONS = frozenset({"txt", "docx", "html", "pdf"})
MAX_EXPORT_SNAPSHOT_BYTES = 64 * 1024 * 1024
_LEGACY_WARNING_PATTERN = re.compile(
    r"^(?P<code>[^:]+): (?P<message>.*) "
    r"\[issue_id=(?P<issue_id>[0-9a-fA-F-]{36}); block_id=(?P<block_id>.+)\]$"
)
_LEGACY_WARNING_ISSUE_ID = UUID(int=0)


class ExportType(StrEnum):
    MODIFIED_DOCUMENT = "modified_document"
    HTML_REPORT = "html_report"
    PDF_REPORT = "pdf_report"


class ExportStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ExportDispatchStatus(StrEnum):
    DISPATCHED = "dispatched"
    DEFERRED = "deferred"


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


class ExportSnapshotTooLarge(ValueError):
    def __init__(self, *, actual_bytes: int, maximum_bytes: int) -> None:
        self.actual_bytes = actual_bytes
        self.maximum_bytes = maximum_bytes
        super().__init__(
            f"Export snapshot is {actual_bytes} bytes; maximum is {maximum_bytes} bytes."
        )


class ExportWarning(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1)
    issue_id: UUID
    block_id: str = Field(min_length=1, max_length=64)


class ExportCheckerFailureSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: CheckCategory
    code: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1)


class ExportIssueSummarySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    total: int = Field(ge=0)
    by_category: dict[CheckCategory, int]
    by_severity: dict[IssueSeverity, int]
    by_decision: dict[str, int]


class ExportSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1, 2] = 2
    document_version_id: UUID | None = None
    decision_snapshot_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    captured_at: datetime
    source_name: str = Field(min_length=1, max_length=255)
    source_type: FileType
    source_size_bytes: int = Field(ge=0)
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    scenario: CheckScenario
    enabled_categories: list[CheckCategory]
    completed_categories: list[CheckCategory]
    checker_failures: list[ExportCheckerFailureSnapshot]
    summary: ExportIssueSummarySnapshot
    document: DocumentModel
    issues: list[Issue]
    preflight_warnings: list[ExportWarning]

    @model_validator(mode="after")
    def validate_source(self) -> ExportSnapshot:
        if self.schema_version == 2 and (
            self.document_version_id is None
            or self.decision_snapshot_sha256 is None
        ):
            raise ValueError(
                "schema-v2 export snapshots require document version and decision hash"
            )
        if self.document.file_type != self.source_type:
            raise ValueError("snapshot source type must match the normalized document")
        if self.document.source_name != self.source_name:
            raise ValueError("snapshot source name must match the normalized document")
        if self.source_type == FileType.DOCX and self.source_sha256 is None:
            raise ValueError("DOCX export snapshots require a source digest")
        return self


class ExportPublicRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    export_id: UUID
    job_id: UUID
    export_type: ExportType
    status: ExportStatus
    file_name: str = Field(min_length=1, max_length=255)
    warnings: list[ExportWarning] = Field(default_factory=list)
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
    def validate_state(self) -> ExportPublicRead:
        _validate_export_state(
            export_id=self.export_id,
            job_id=self.job_id,
            export_type=self.export_type,
            status=self.status,
            file_name=self.file_name,
            error_code=self.error_code,
            error_message=self.error_message,
        )
        return self


class ExportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    export_id: UUID
    job_id: UUID
    export_type: ExportType
    status: ExportStatus
    file_name: str = Field(min_length=1, max_length=255)
    storage_key: str = Field(min_length=1, max_length=255)
    warnings: list[ExportWarning] = Field(default_factory=list)
    snapshot: ExportSnapshot | None = None
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
        _validate_export_state(
            job_id=self.job_id,
            export_id=self.export_id,
            export_type=self.export_type,
            status=self.status,
            file_name=self.file_name,
            storage_key=self.storage_key,
            error_code=self.error_code,
            error_message=self.error_message,
        )
        return self


def _validate_export_state(
    *,
    export_id: UUID,
    job_id: UUID,
    export_type: ExportType,
    status: ExportStatus,
    file_name: str,
    error_code: str | None,
    error_message: str | None,
    storage_key: str | None = None,
) -> None:
    file_name_extension = Path(file_name).suffix.removeprefix(".")
    expected_artifact = build_export_artifact(
        job_id=job_id,
        export_id=export_id,
        export_type=export_type,
        extension=file_name_extension,
    )
    if file_name != expected_artifact.file_name:
        raise ValueError("export file_name must use the server-generated value")
    if storage_key is not None and storage_key != expected_artifact.storage_key:
        raise ValueError("export storage_key must use the server-generated value")
    if status == ExportStatus.FAILED:
        if error_code is None or error_message is None:
            raise ValueError("failed exports must include error details")
        return
    if error_code is not None or error_message is not None:
        raise ValueError("non-failed exports must not include error details")


def serialize_export_snapshot(
    snapshot: ExportSnapshot,
    *,
    maximum_bytes: int = MAX_EXPORT_SNAPSHOT_BYTES,
) -> dict[str, Any]:
    if maximum_bytes <= 0:
        raise ValueError("maximum_bytes must be positive")
    encoded = snapshot.model_dump_json()
    actual_bytes = len(encoded.encode("utf-8"))
    if actual_bytes > maximum_bytes:
        raise ExportSnapshotTooLarge(
            actual_bytes=actual_bytes,
            maximum_bytes=maximum_bytes,
        )
    value = json.loads(encoded)
    if not isinstance(value, dict):
        raise ValueError("serialized export snapshot must be an object")
    return value


def deserialize_export_snapshot(value: object) -> ExportSnapshot | None:
    if value is None:
        return None
    if isinstance(value, dict) and value.get("schema_version") == 1:
        return _deserialize_schema_v1_export_snapshot(value)
    return ExportSnapshot.model_validate(value)


def _deserialize_schema_v1_export_snapshot(value: dict[str, Any]) -> ExportSnapshot:
    raw_issues = value.get("issues", [])
    if not isinstance(raw_issues, list):
        return ExportSnapshot.model_validate(value)

    snapshot_payload = {**value, "issues": []}
    snapshot = ExportSnapshot.model_validate(snapshot_payload)
    issues = [_deserialize_schema_v1_issue(issue) for issue in raw_issues]
    return snapshot.model_copy(update={"issues": issues})


def _deserialize_schema_v1_issue(value: object) -> Issue:
    if not isinstance(value, dict):
        return Issue.model_validate(value)

    raw_decision = value.get("decision")
    issue = Issue.model_validate({**value, "decision": None})
    decision = _deserialize_schema_v1_decision(raw_decision)
    if decision is None:
        return issue
    return issue.model_copy(update={"decision": decision})


def _deserialize_schema_v1_decision(value: object) -> IssueDecisionSummary | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        return IssueDecisionSummary.model_validate(value)

    normalized = dict(value)
    if normalized.get("action") == "custom":
        normalized["action"] = DecisionAction.ACCEPTED.value

    if (
        normalized.get("action") == DecisionAction.ACCEPTED.value
        and normalized.get("replacement") is None
    ):
        return IssueDecisionSummary.model_construct(
            issue_version=int(normalized["issue_version"]),
            revision=int(normalized.get("revision", 0)),
            action=DecisionAction.ACCEPTED,
            replacement=None,
            suggestion_id=_optional_uuid(normalized.get("suggestion_id")),
            updated_at=_parse_datetime(normalized["updated_at"]),
        )

    return IssueDecisionSummary.model_validate(normalized)


def _optional_uuid(value: object) -> UUID | None:
    if value is None or isinstance(value, UUID):
        return value
    return UUID(str(value))


def _parse_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise ValueError("updated_at must be a datetime")


def serialize_export_warnings(
    warnings: list[ExportWarning] | tuple[ExportWarning, ...],
) -> list[object]:
    return [warning.model_dump(mode="json") for warning in warnings]


def deserialize_export_warnings(values: object) -> list[ExportWarning]:
    if not isinstance(values, list):
        raise ValueError("export warnings must be a list")
    return [_deserialize_export_warning(value) for value in values]


def _deserialize_export_warning(value: object) -> ExportWarning:
    if isinstance(value, dict):
        return ExportWarning.model_validate(value)
    if not isinstance(value, str):
        raise ValueError("export warning must be an object")

    matched = _LEGACY_WARNING_PATTERN.fullmatch(value)
    if matched is not None:
        return ExportWarning(
            code=matched.group("code"),
            message=matched.group("message"),
            issue_id=UUID(matched.group("issue_id")),
            block_id=matched.group("block_id"),
        )
    return ExportWarning(
        code="legacy_export_warning",
        message=value,
        issue_id=_LEGACY_WARNING_ISSUE_ID,
        block_id="legacy",
    )
