from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from text_verification.domain.documents import FileType


class ArtifactLifecycleStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"


@dataclass(frozen=True)
class ArtifactReservation:
    export_artifact_id: UUID
    job_id: UUID
    verification_run_id: UUID
    review_revision_id: UUID | None
    source_version: str
    file_type: FileType
    file_name: str
    media_type: str
    storage_key: str
    size_bytes: int
    content_sha256: str
    status: ArtifactLifecycleStatus
    reserved_at: datetime
    created_at: datetime


@dataclass(frozen=True)
class ArtifactSnapshot:
    export_artifact_id: UUID
    job_id: UUID
    verification_run_id: UUID
    review_revision_id: UUID | None
    source_version: str
    file_type: FileType
    file_name: str
    media_type: str
    storage_key: str
    size_bytes: int
    content_sha256: str | None
    status: ArtifactLifecycleStatus
    reserved_at: datetime
    ready_at: datetime | None
    created_at: datetime
