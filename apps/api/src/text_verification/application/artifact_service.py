from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

from text_verification.domain.documents import FileType
from text_verification.infrastructure.storage import (
    JobStorage,
    PublishedArtifact,
    VerifiedArtifact,
)

logger = logging.getLogger(__name__)


class ArtifactRepository(Protocol):
    def save_export_artifact(
        self,
        *,
        export_artifact_id: UUID,
        verification_run_id: UUID,
        review_revision_id: UUID | None,
        source_version: str,
        file_name: str,
        media_type: str,
        artifact: PublishedArtifact,
        created_at: datetime,
    ) -> VerifiedArtifact: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


@dataclass(frozen=True)
class ArtifactPersistenceRequest:
    job_id: UUID
    export_artifact_id: UUID
    verification_run_id: UUID
    review_revision_id: UUID | None
    source_version: str
    file_type: FileType
    file_name: str
    media_type: str
    storage_key: str
    data: bytes
    created_at: datetime


@dataclass(frozen=True)
class ArtifactPersistenceResult:
    export_artifact_id: UUID
    job_id: UUID
    storage_key: str
    path: Path
    file_type: FileType
    size_bytes: int
    content_sha256: str
    created: bool


class ArtifactPersistenceService:
    """Coordinate storage publication and database persistence.

    Filesystem publication and a database commit cannot share one atomic
    transaction. Compensation therefore removes only a newly published file
    whose fingerprint is still unchanged; an ambiguous commit outcome may
    require orphan-sweep or operator reconciliation.
    """

    def __init__(
        self,
        storage: JobStorage,
        repository: ArtifactRepository,
    ) -> None:
        self._storage = storage
        self._repository = repository

    def persist(
        self,
        request: ArtifactPersistenceRequest,
    ) -> ArtifactPersistenceResult:
        published = self._storage.publish_artifact(
            request.job_id,
            request.export_artifact_id,
            request.storage_key,
            request.file_type,
            request.data,
        )
        try:
            verified = self._repository.save_export_artifact(
                export_artifact_id=request.export_artifact_id,
                verification_run_id=request.verification_run_id,
                review_revision_id=request.review_revision_id,
                source_version=request.source_version,
                file_name=request.file_name,
                media_type=request.media_type,
                artifact=published,
                created_at=request.created_at,
            )
            self._repository.commit()
        except Exception:
            try:
                self._repository.rollback()
            except Exception as rollback_error:
                logger.warning(
                    "artifact_persistence_rollback_failed",
                    extra={"error_type": type(rollback_error).__name__},
                )
            compensated = self._storage.compensate_published_artifact(published)
            if published.created and not compensated:
                logger.warning(
                    "artifact_persistence_compensation_skipped",
                    extra={
                        "storage_key": published.storage_key,
                        "reason": "missing_or_fingerprint_changed",
                    },
                )
            raise

        return ArtifactPersistenceResult(
            export_artifact_id=request.export_artifact_id,
            job_id=verified.job_id,
            storage_key=verified.storage_key,
            path=verified.path,
            file_type=verified.file_type,
            size_bytes=verified.size_bytes,
            content_sha256=verified.content_sha256,
            created=verified.created,
        )
