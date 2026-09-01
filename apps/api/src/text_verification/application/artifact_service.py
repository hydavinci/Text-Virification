from __future__ import annotations

import hashlib
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

from text_verification.domain.artifacts import (
    ArtifactLifecycleStatus,
    ArtifactReservation,
    ArtifactSnapshot,
)
from text_verification.domain.documents import FileType
from text_verification.infrastructure.artifact_storage import (
    ArtifactNotFoundError,
    ArtifactVerificationHandle,
)
from text_verification.infrastructure.storage import JobStorage


class ArtifactReconciliationRequiredError(RuntimeError):
    def __init__(self, export_artifact_id: UUID, message: str) -> None:
        self.export_artifact_id = export_artifact_id
        super().__init__(message)


class ArtifactRepository(Protocol):
    def reserve_export_artifact(
        self,
        *,
        export_artifact_id: UUID,
        verification_run_id: UUID,
        review_revision_id: UUID | None,
        source_version: str,
        file_type: FileType,
        file_name: str,
        media_type: str,
        storage_key: str,
        size_bytes: int,
        content_sha256: str,
        reserved_at: datetime,
        created_at: datetime,
    ) -> ArtifactReservation: ...

    def finalize_export_artifact(
        self,
        reservation: ArtifactReservation,
        *,
        ready_at: datetime,
        consistency_check: Callable[[], None],
    ) -> ArtifactSnapshot: ...

    def read_export_artifact(
        self,
        export_artifact_id: UUID,
    ) -> ArtifactSnapshot | None: ...

    def list_stale_pending_artifacts(
        self,
        older_than: datetime,
    ) -> tuple[ArtifactSnapshot, ...]: ...

    def delete_pending_export_artifact(
        self,
        *,
        export_artifact_id: UUID,
        content_sha256: str,
    ) -> bool: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


ArtifactRepositoryFactory = Callable[
    [],
    AbstractContextManager[ArtifactRepository],
]


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


@dataclass(frozen=True)
class ArtifactPendingReconciliationResult:
    ready_artifact_ids: tuple[UUID, ...]
    deleted_artifact_ids: tuple[UUID, ...]
    deferred_artifact_ids: tuple[UUID, ...]


class ArtifactPersistenceService:
    """Persist artifacts through a pending database reservation.

    The pending reservation commits before filesystem publication, so cleanup
    treats in-flight keys as referenced. A retained descriptor chain proves the
    canonical directory entries still name the hashed inode before and after
    the short finalize transaction.
    """

    def __init__(
        self,
        storage: JobStorage,
        repository_factory: ArtifactRepositoryFactory,
        *,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self._storage = storage
        self._repository_factory = repository_factory
        self._now_factory = now_factory or (lambda: datetime.now(UTC))

    def persist(
        self,
        request: ArtifactPersistenceRequest,
    ) -> ArtifactPersistenceResult:
        size_bytes = len(request.data)
        content_sha256 = hashlib.sha256(request.data).hexdigest()
        reservation = self._reserve(
            request,
            size_bytes=size_bytes,
            content_sha256=content_sha256,
        )

        with self._storage.publish_verified_artifact(
            request.job_id,
            request.export_artifact_id,
            request.storage_key,
            request.file_type,
            request.data,
        ) as handle:
            if (
                handle.size_bytes != reservation.size_bytes
                or handle.content_sha256 != reservation.content_sha256
            ):
                raise ArtifactReconciliationRequiredError(
                    request.export_artifact_id,
                    "Published artifact does not match its pending reservation.",
                )
            snapshot = self._finalize(reservation, handle)
            return ArtifactPersistenceResult(
                export_artifact_id=snapshot.export_artifact_id,
                job_id=snapshot.job_id,
                storage_key=snapshot.storage_key,
                path=handle.path,
                file_type=snapshot.file_type,
                size_bytes=snapshot.size_bytes,
                content_sha256=reservation.content_sha256,
                created=handle.created,
            )

    def _reserve(
        self,
        request: ArtifactPersistenceRequest,
        *,
        size_bytes: int,
        content_sha256: str,
    ) -> ArtifactReservation:
        reserved_at = self._now_factory()
        with self._repository_factory() as repository:
            try:
                reservation = repository.reserve_export_artifact(
                    export_artifact_id=request.export_artifact_id,
                    verification_run_id=request.verification_run_id,
                    review_revision_id=request.review_revision_id,
                    source_version=request.source_version,
                    file_type=request.file_type,
                    file_name=request.file_name,
                    media_type=request.media_type,
                    storage_key=request.storage_key,
                    size_bytes=size_bytes,
                    content_sha256=content_sha256,
                    reserved_at=reserved_at,
                    created_at=request.created_at,
                )
            except Exception:
                repository.rollback()
                raise
            try:
                repository.commit()
            except Exception as error:
                repository.rollback()
                try:
                    snapshot = self._read_fresh(request.export_artifact_id)
                except Exception as probe_error:
                    raise ArtifactReconciliationRequiredError(
                        request.export_artifact_id,
                        "Artifact reservation commit outcome could not be read.",
                    ) from probe_error
                if snapshot is None:
                    raise
                if not _snapshot_matches_request(
                    snapshot,
                    request,
                    size_bytes=size_bytes,
                    content_sha256=content_sha256,
                    allow_legacy_digest=True,
                ):
                    raise ArtifactReconciliationRequiredError(
                        request.export_artifact_id,
                        "Artifact reservation commit outcome cannot be proved.",
                    ) from error
                return _reservation_from_snapshot(
                    snapshot,
                    expected_content_sha256=content_sha256,
                )
            return reservation

    def _finalize(
        self,
        reservation: ArtifactReservation,
        handle: ArtifactVerificationHandle,
    ) -> ArtifactSnapshot:
        with self._repository_factory() as repository:
            try:
                snapshot = repository.finalize_export_artifact(
                    reservation,
                    ready_at=self._now_factory(),
                    consistency_check=handle.assert_current,
                )
            except Exception:
                repository.rollback()
                self._compensate_known_pending(handle, reservation)
                raise
            try:
                repository.commit()
            except Exception as error:
                repository.rollback()
                return self._resolve_finalize_commit(
                    reservation,
                    handle,
                    error,
                )

        try:
            handle.assert_current()
        except Exception as error:
            raise ArtifactReconciliationRequiredError(
                reservation.export_artifact_id,
                "Artifact changed immediately after finalize commit.",
            ) from error
        return snapshot

    def _resolve_finalize_commit(
        self,
        reservation: ArtifactReservation,
        handle: ArtifactVerificationHandle,
        commit_error: Exception,
    ) -> ArtifactSnapshot:
        try:
            snapshot = self._read_fresh(reservation.export_artifact_id)
        except Exception as probe_error:
            raise ArtifactReconciliationRequiredError(
                reservation.export_artifact_id,
                "Artifact finalize commit outcome could not be read.",
            ) from probe_error
        if (
            snapshot is not None
            and snapshot.status is ArtifactLifecycleStatus.READY
            and _snapshot_matches_reservation(snapshot, reservation)
        ):
            try:
                handle.assert_current()
            except Exception as error:
                raise ArtifactReconciliationRequiredError(
                    reservation.export_artifact_id,
                    "Ready metadata exists but the artifact entry changed.",
                ) from error
            return snapshot

        if snapshot is None or (
            snapshot.status is ArtifactLifecycleStatus.PENDING
            and _snapshot_matches_reservation(snapshot, reservation)
        ):
            self._compensate_known_pending(handle, reservation)
            raise commit_error

        raise ArtifactReconciliationRequiredError(
            reservation.export_artifact_id,
            "Artifact finalize commit outcome cannot be proved.",
        ) from commit_error

    def _compensate_known_pending(
        self,
        handle: ArtifactVerificationHandle,
        reservation: ArtifactReservation,
    ) -> None:
        if not handle.created:
            return
        try:
            handle.unlink_created_if_current()
        except Exception as error:
            raise ArtifactReconciliationRequiredError(
                reservation.export_artifact_id,
                "New artifact could not be safely compensated.",
            ) from error

    def _read_fresh(self, export_artifact_id: UUID) -> ArtifactSnapshot | None:
        with self._repository_factory() as repository:
            try:
                return repository.read_export_artifact(export_artifact_id)
            finally:
                repository.rollback()


def _reservation_from_snapshot(
    snapshot: ArtifactSnapshot,
    *,
    expected_content_sha256: str,
) -> ArtifactReservation:
    return ArtifactReservation(
        export_artifact_id=snapshot.export_artifact_id,
        job_id=snapshot.job_id,
        verification_run_id=snapshot.verification_run_id,
        review_revision_id=snapshot.review_revision_id,
        source_version=snapshot.source_version,
        file_type=snapshot.file_type,
        file_name=snapshot.file_name,
        media_type=snapshot.media_type,
        storage_key=snapshot.storage_key,
        size_bytes=snapshot.size_bytes,
        content_sha256=snapshot.content_sha256 or expected_content_sha256,
        status=snapshot.status,
        reserved_at=snapshot.reserved_at,
        created_at=snapshot.created_at,
    )


def _snapshot_matches_request(
    snapshot: ArtifactSnapshot,
    request: ArtifactPersistenceRequest,
    *,
    size_bytes: int,
    content_sha256: str,
    allow_legacy_digest: bool,
) -> bool:
    return (
        snapshot.export_artifact_id == request.export_artifact_id
        and snapshot.job_id == request.job_id
        and snapshot.verification_run_id == request.verification_run_id
        and snapshot.review_revision_id == request.review_revision_id
        and snapshot.source_version == request.source_version
        and snapshot.file_type is request.file_type
        and snapshot.file_name == request.file_name
        and snapshot.media_type == request.media_type
        and snapshot.storage_key == request.storage_key
        and snapshot.size_bytes == size_bytes
        and (
            snapshot.content_sha256 == content_sha256
            or (allow_legacy_digest and snapshot.content_sha256 is None)
        )
        and snapshot.created_at == request.created_at
    )


def _snapshot_matches_reservation(
    snapshot: ArtifactSnapshot,
    reservation: ArtifactReservation,
) -> bool:
    return (
        snapshot.export_artifact_id == reservation.export_artifact_id
        and snapshot.job_id == reservation.job_id
        and snapshot.verification_run_id == reservation.verification_run_id
        and snapshot.review_revision_id == reservation.review_revision_id
        and snapshot.source_version == reservation.source_version
        and snapshot.file_type is reservation.file_type
        and snapshot.file_name == reservation.file_name
        and snapshot.media_type == reservation.media_type
        and snapshot.storage_key == reservation.storage_key
        and snapshot.size_bytes == reservation.size_bytes
        and snapshot.content_sha256 == reservation.content_sha256
        and snapshot.created_at == reservation.created_at
    )


class ArtifactPendingReconciliationService:
    def __init__(
        self,
        storage: JobStorage,
        repository_factory: ArtifactRepositoryFactory,
        *,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self._storage = storage
        self._repository_factory = repository_factory
        self._now_factory = now_factory or (lambda: datetime.now(UTC))

    def reconcile_before(
        self,
        older_than: datetime,
    ) -> ArtifactPendingReconciliationResult:
        with self._repository_factory() as repository:
            try:
                pending = repository.list_stale_pending_artifacts(older_than)
            finally:
                repository.rollback()

        ready_ids: list[UUID] = []
        deleted_ids: list[UUID] = []
        deferred_ids: list[UUID] = []
        for snapshot in pending:
            if snapshot.content_sha256 is None:
                deferred_ids.append(snapshot.export_artifact_id)
                continue
            reservation = _reservation_from_snapshot(
                snapshot,
                expected_content_sha256=snapshot.content_sha256,
            )
            try:
                handle = self._storage.open_verified_artifact(
                    snapshot.job_id,
                    snapshot.export_artifact_id,
                    snapshot.storage_key,
                    snapshot.file_type,
                    expected_size=snapshot.size_bytes,
                    expected_digest=snapshot.content_sha256,
                )
            except ArtifactNotFoundError:
                with self._repository_factory() as repository:
                    try:
                        deleted = repository.delete_pending_export_artifact(
                            export_artifact_id=snapshot.export_artifact_id,
                            content_sha256=snapshot.content_sha256,
                        )
                        repository.commit()
                    except Exception:
                        repository.rollback()
                        raise
                if deleted:
                    deleted_ids.append(snapshot.export_artifact_id)
                continue
            except Exception:
                deferred_ids.append(snapshot.export_artifact_id)
                continue

            with handle:
                try:
                    with self._repository_factory() as repository:
                        try:
                            repository.finalize_export_artifact(
                                reservation,
                                ready_at=self._now_factory(),
                                consistency_check=handle.assert_current,
                            )
                            repository.commit()
                        except Exception:
                            repository.rollback()
                            raise
                    handle.assert_current()
                except Exception:
                    deferred_ids.append(snapshot.export_artifact_id)
                    continue
            ready_ids.append(snapshot.export_artifact_id)

        return ArtifactPendingReconciliationResult(
            ready_artifact_ids=tuple(ready_ids),
            deleted_artifact_ids=tuple(deleted_ids),
            deferred_artifact_ids=tuple(deferred_ids),
        )
