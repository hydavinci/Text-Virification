from __future__ import annotations

import hashlib
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from text_verification.application.artifact_service import (
    ArtifactFinalizationRejectedError,
    ArtifactPersistenceRequest,
    ArtifactPersistenceService,
    ArtifactReconciliationRequiredError,
    ArtifactRepository,
    ArtifactRepositoryFactory,
)
from text_verification.application.errors import VerificationError
from text_verification.compatibility.exporters import ExportError
from text_verification.domain.artifacts import (
    ArtifactLifecycleStatus,
    ArtifactReservation,
    ArtifactSnapshot,
    ExportArtifactReference,
)
from text_verification.domain.documents import DocumentModel, ExportFormat, FileType
from text_verification.domain.jobs import JobProgressStage, JobRead
from text_verification.domain.ports import AnchoredSourcePathResolver
from text_verification.domain.verification import VerificationResult
from text_verification.exporters.docx_reconstruction import DocxReconstructionExporter
from text_verification.exporters.registry import ExporterRegistry
from text_verification.infrastructure.artifact_storage import (
    ArtifactNotFoundError,
    ArtifactVerificationHandle,
)
from text_verification.infrastructure.storage import (
    InvalidUpload,
    JobOwnedSourcePathResolver,
    JobStorage,
    build_artifact_storage_key,
)
from text_verification.infrastructure.verification_repository import (
    JobResultSnapshot,
    JobResultState,
)

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
ExportProgressObserver = Callable[[JobProgressStage], None]
ExporterRegistryFactory = Callable[[AnchoredSourcePathResolver], ExporterRegistry]


class ReconstructionRepository(ArtifactRepository, Protocol):
    def read_result_snapshot(self, job_id: UUID) -> JobResultSnapshot: ...

    def read_export_artifact(
        self,
        export_artifact_id: UUID,
    ) -> ArtifactSnapshot | None: ...


ReconstructionRepositoryFactory = Callable[
    [],
    AbstractContextManager[ReconstructionRepository],
]


@dataclass(frozen=True)
class ArtifactDownload:
    handle: ArtifactVerificationHandle
    file_name: str
    media_type: str

    @property
    def path(self) -> Path:
        return self.handle.path


class ReconstructionExportService:
    def __init__(
        self,
        storage: JobStorage,
        repository_factory: ReconstructionRepositoryFactory,
        *,
        exporter_registry_factory: ExporterRegistryFactory,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self._storage = storage
        self._repository_factory = repository_factory
        self._exporter_registry_factory = exporter_registry_factory
        self._now_factory = now_factory or (lambda: datetime.now(UTC))

    def export(
        self,
        job: JobRead,
        export_format: ExportFormat,
        *,
        progress_observer: ExportProgressObserver | None = None,
    ) -> ExportArtifactReference:
        if export_format is not ExportFormat.DOCX_RECONSTRUCTION:
            raise VerificationError(
                "unsupported_export_format",
                "exporting",
                "The requested export format is not supported.",
                False,
            )
        result = self._load_result(job.job_id)
        document = _document_from_result(result)
        _validate_reconstruction_eligibility(document)

        artifact_id = _artifact_id(job, result.verification_run_id, export_format)
        file_name = _file_name(job.source_name)
        storage_key = build_artifact_storage_key(job.job_id, artifact_id, FileType.DOCX)
        existing = self._read_artifact(artifact_id)
        repair_candidate = existing is not None
        if existing is not None and existing.status is ArtifactLifecycleStatus.READY:
            reference = _reference_from_snapshot(
                existing,
                job=job,
                verification_run_id=result.verification_run_id,
                export_format=export_format,
                file_name=file_name,
                storage_key=storage_key,
            )
            try:
                with self._storage.open_verified_artifact(
                    existing.job_id,
                    existing.export_artifact_id,
                    existing.storage_key,
                    existing.file_type,
                    expected_size=existing.size_bytes,
                    expected_digest=reference.content_sha256,
                ):
                    pass
            except InvalidUpload:
                pass
            else:
                self._delete_repair_quarantine(
                    existing.job_id,
                    existing.export_artifact_id,
                    existing.storage_key,
                    existing.file_type,
                )
                return reference

        if progress_observer is not None:
            progress_observer(JobProgressStage.EXPORTING)
        resolver = JobOwnedSourcePathResolver(
            self._storage,
            job.job_id,
            document.file_type,
        )
        registry = self._exporter_registry_factory(resolver)
        exporter = cast(
            DocxReconstructionExporter,
            registry.get(ExportFormat.DOCX_RECONSTRUCTION),
        )
        work_path = (
            self._storage.job_directory(job.job_id)
            / f".{uuid4().hex}.reconstructing.docx"
        )
        try:
            try:
                exporter.export(document, work_path)
                data = work_path.read_bytes()
            except (ExportError, OSError, ValueError) as error:
                raise VerificationError(
                    "document_reconstruction_failed",
                    "exporting",
                    "The canonical document could not be reconstructed.",
                    False,
                ) from error
        finally:
            try:
                work_path.unlink(missing_ok=True)
            except OSError as error:
                raise VerificationError(
                    "export_workspace_cleanup_failed",
                    "finalizing",
                    "The export workspace could not be cleaned safely.",
                    True,
                ) from error

        request = ArtifactPersistenceRequest(
            job_id=job.job_id,
            export_artifact_id=artifact_id,
            verification_run_id=result.verification_run_id,
            review_revision_id=None,
            source_version=result.source_version,
            file_type=FileType.DOCX,
            file_name=file_name,
            media_type=DOCX_MEDIA_TYPE,
            storage_key=storage_key,
            data=data,
            created_at=job.created_at,
        )
        self._assert_current_result(job.job_id, result)
        if repair_candidate:
            self._begin_repair(request)
        if progress_observer is not None:
            progress_observer(JobProgressStage.FINALIZING)
        try:
            persisted = ArtifactPersistenceService(
                self._storage,
                cast(ArtifactRepositoryFactory, self._repository_factory),
                require_current_result=True,
            ).persist(request)
        except ArtifactFinalizationRejectedError as error:
            raise VerificationError(
                "job_result_expired",
                "finalizing",
                "Job result has expired.",
                False,
            ) from error
        except ArtifactReconciliationRequiredError as error:
            if repair_candidate:
                raise VerificationError(
                    "export_artifact_repair_pending",
                    "finalizing",
                    "The export artifact repair is incomplete and can be retried.",
                    True,
                ) from error
            raise VerificationError(
                "export_finalization_uncertain",
                "finalizing",
                "The export artifact requires reconciliation.",
                True,
            ) from error
        except Exception as error:
            if repair_candidate:
                raise VerificationError(
                    "export_artifact_repair_pending",
                    "finalizing",
                    "The export artifact repair is incomplete and can be retried.",
                    True,
                ) from error
            raise VerificationError(
                "export_persistence_failed",
                "finalizing",
                "The export artifact could not be persisted.",
                True,
            ) from error
        self._delete_repair_quarantine(
            persisted.job_id,
            persisted.export_artifact_id,
            persisted.storage_key,
            persisted.file_type,
        )
        return ExportArtifactReference(
            export_artifact_id=persisted.export_artifact_id,
            job_id=persisted.job_id,
            verification_run_id=result.verification_run_id,
            format=export_format,
            file_type=persisted.file_type,
            file_name=file_name,
            media_type=DOCX_MEDIA_TYPE,
            size_bytes=persisted.size_bytes,
            content_sha256=persisted.content_sha256,
            status=ArtifactLifecycleStatus.READY,
            created_at=job.created_at,
        )

    def download(
        self,
        job_id: UUID,
        export_artifact_id: UUID,
    ) -> ArtifactDownload:
        handle: ArtifactVerificationHandle | None = None
        with self._repository_factory() as repository:
            try:
                result_snapshot = repository.read_result_snapshot(job_id)
                result = self._download_result(result_snapshot)
                artifact = repository.read_export_artifact(export_artifact_id)
                if artifact is None or not _artifact_belongs_to_result(
                    artifact,
                    job_id,
                    result,
                ):
                    raise VerificationError(
                        "export_artifact_not_found",
                        "exporting",
                        "The export artifact was not found.",
                        False,
                    )
                if (
                    artifact.status is not ArtifactLifecycleStatus.READY
                    or artifact.content_sha256 is None
                ):
                    raise VerificationError(
                        "export_artifact_pending",
                        "finalizing",
                        "The export artifact is not ready.",
                        True,
                    )
                _validate_reconstruction_eligibility(_document_from_result(result))
                try:
                    handle = self._storage.open_verified_artifact(
                        artifact.job_id,
                        artifact.export_artifact_id,
                        artifact.storage_key,
                        artifact.file_type,
                        expected_size=artifact.size_bytes,
                        expected_digest=artifact.content_sha256,
                    )
                except (ArtifactNotFoundError, InvalidUpload) as error:
                    raise VerificationError(
                        "export_artifact_unavailable",
                        "finalizing",
                        "The export artifact is unavailable.",
                        True,
                    ) from error
            finally:
                try:
                    repository.rollback()
                except Exception:
                    if handle is not None:
                        handle.close()
                    raise
        if handle is None:
            raise AssertionError("authorized artifact download must retain a descriptor")
        return ArtifactDownload(handle, artifact.file_name, artifact.media_type)

    def _load_result(self, job_id: UUID) -> VerificationResult:
        with self._repository_factory() as repository:
            try:
                snapshot = repository.read_result_snapshot(job_id)
            finally:
                repository.rollback()
        if snapshot.state in {
            JobResultState.MISSING,
            JobResultState.EXPIRED,
            JobResultState.UNAVAILABLE,
        }:
            raise VerificationError(
                "job_result_expired",
                "exporting",
                "Job result has expired.",
                False,
            )
        if snapshot.state is not JobResultState.READY or snapshot.result is None:
            raise VerificationError(
                "job_result_unavailable",
                "exporting",
                "The job has no canonical result available for export.",
                False,
            )
        return snapshot.result

    def _assert_current_result(
        self,
        job_id: UUID,
        expected: VerificationResult,
    ) -> None:
        current = self._load_result(job_id)
        if (
            current.verification_run_id != expected.verification_run_id
            or current.document_id != expected.document_id
            or current.source_version != expected.source_version
        ):
            raise VerificationError(
                "export_source_superseded",
                "finalizing",
                "The verification result was superseded before export.",
                False,
            )

    def _read_artifact(self, export_artifact_id: UUID) -> ArtifactSnapshot | None:
        with self._repository_factory() as repository:
            try:
                return repository.read_export_artifact(export_artifact_id)
            finally:
                repository.rollback()

    def _begin_repair(self, request: ArtifactPersistenceRequest) -> None:
        digest = hashlib.sha256(request.data).hexdigest()
        expected = ArtifactReservation(
            export_artifact_id=request.export_artifact_id,
            job_id=request.job_id,
            verification_run_id=request.verification_run_id,
            review_revision_id=request.review_revision_id,
            source_version=request.source_version,
            file_type=request.file_type,
            file_name=request.file_name,
            media_type=request.media_type,
            storage_key=request.storage_key,
            size_bytes=len(request.data),
            content_sha256=digest,
            status=ArtifactLifecycleStatus.PENDING,
            reserved_at=self._now_factory(),
            created_at=request.created_at,
        )
        with self._repository_factory() as repository:
            try:
                repository.begin_export_artifact_repair(
                    expected,
                    consistency_check=lambda: self._storage.prepare_artifact_repair(
                        request.job_id,
                        request.export_artifact_id,
                        request.storage_key,
                        request.file_type,
                        expected_size=len(request.data),
                        expected_digest=digest,
                    ),
                )
                repository.commit()
            except InvalidUpload as error:
                repository.rollback()
                raise VerificationError(
                    "export_artifact_repair_unsafe",
                    "finalizing",
                    "The corrupt export artifact cannot be repaired safely.",
                    False,
                ) from error
            except ValueError as error:
                repository.rollback()
                raise VerificationError(
                    "export_artifact_conflict",
                    "finalizing",
                    "The existing export artifact does not match this request.",
                    False,
                ) from error
            except Exception as error:
                repository.rollback()
                raise VerificationError(
                    "export_artifact_repair_pending",
                    "finalizing",
                    "The export artifact repair is incomplete and can be retried.",
                    True,
                ) from error

    def _delete_repair_quarantine(
        self,
        job_id: UUID,
        export_artifact_id: UUID,
        storage_key: str,
        file_type: FileType,
    ) -> None:
        try:
            self._storage.delete_artifact_repair_quarantine(
                job_id,
                export_artifact_id,
                storage_key,
                file_type,
            )
        except (InvalidUpload, OSError) as error:
            raise VerificationError(
                "export_artifact_repair_cleanup_failed",
                "finalizing",
                "The repaired artifact quarantine could not be removed safely.",
                True,
            ) from error

    @staticmethod
    def _download_result(snapshot: JobResultSnapshot) -> VerificationResult:
        if snapshot.state in {
            JobResultState.MISSING,
            JobResultState.EXPIRED,
            JobResultState.UNAVAILABLE,
        }:
            raise VerificationError(
                "job_result_expired",
                "exporting",
                "Job result has expired.",
                False,
            )
        if snapshot.state is not JobResultState.READY or snapshot.result is None:
            raise VerificationError(
                "job_result_unavailable",
                "exporting",
                "The job has no canonical result available for export.",
                False,
            )
        return snapshot.result


def _document_from_result(result: VerificationResult) -> DocumentModel:
    return DocumentModel(
        document_id=result.document_id,
        source_version=result.source_version,
        file_type=result.file_type,
        source_name=result.source_name,
        text=result.text,
        blocks=list(result.blocks),
        parser_name=result.parser_name,
        parser_version=result.parser_version,
        metadata=result.metadata,
    )


def _validate_reconstruction_eligibility(document: DocumentModel) -> None:
    if (
        document.file_type is not FileType.PDF
        or document.metadata.pdf is None
        or not document.blocks
        or not any(
            block.page is not None
            and block.kind in {"paragraph", "heading", "table_cell", "image"}
            for block in document.blocks
        )
    ):
        raise VerificationError(
            "document_not_reconstructable",
            "exporting",
            "The canonical document does not contain reconstructable structure.",
            False,
        )


def _artifact_id(
    job: JobRead,
    verification_run_id: UUID,
    export_format: ExportFormat,
) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        (
            f"export:{job.job_id}:{verification_run_id}:"
            f"{export_format.value}:{job.created_at.isoformat()}"
        ),
    )


def _file_name(source_name: str) -> str:
    stem = Path(source_name).stem.replace("\r", "").replace("\n", "").strip()
    return f"{stem or 'document'}-reconstructed.docx"


def _reference_from_snapshot(
    snapshot: ArtifactSnapshot,
    *,
    job: JobRead,
    verification_run_id: UUID,
    export_format: ExportFormat,
    file_name: str,
    storage_key: str,
) -> ExportArtifactReference:
    expected = (
        job.job_id,
        verification_run_id,
        FileType.DOCX,
        file_name,
        DOCX_MEDIA_TYPE,
        storage_key,
        job.created_at,
    )
    actual = (
        snapshot.job_id,
        snapshot.verification_run_id,
        snapshot.file_type,
        snapshot.file_name,
        snapshot.media_type,
        snapshot.storage_key,
        snapshot.created_at,
    )
    if actual != expected or snapshot.content_sha256 is None:
        raise VerificationError(
            "export_artifact_conflict",
            "finalizing",
            "The existing export artifact does not match this request.",
            False,
        )
    return ExportArtifactReference(
        export_artifact_id=snapshot.export_artifact_id,
        job_id=snapshot.job_id,
        verification_run_id=snapshot.verification_run_id,
        format=export_format,
        file_type=snapshot.file_type,
        file_name=snapshot.file_name,
        media_type=snapshot.media_type,
        size_bytes=snapshot.size_bytes,
        content_sha256=snapshot.content_sha256,
        status=snapshot.status,
        created_at=snapshot.created_at,
    )


def _artifact_belongs_to_result(
    artifact: ArtifactSnapshot,
    job_id: UUID,
    result: VerificationResult,
) -> bool:
    return (
        artifact.job_id == job_id
        and artifact.verification_run_id == result.verification_run_id
        and artifact.review_revision_id is None
        and artifact.source_version == result.source_version
        and artifact.file_type is FileType.DOCX
    )
