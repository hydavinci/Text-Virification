from __future__ import annotations

import hashlib
from bisect import bisect_right
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
from text_verification.application.recheck_provenance import (
    RecheckGrantBinding,
    RecheckGrantError,
    RecheckProvenanceGrantService,
)
from text_verification.compatibility.exporters import ExportError
from text_verification.domain.artifacts import (
    ArtifactFinalizationRejection,
    ArtifactLifecycleStatus,
    ArtifactReservation,
    ArtifactSnapshot,
    ExportArtifactReference,
)
from text_verification.domain.documents import (
    DocumentModel,
    ExportFormat,
    FileType,
    TextBlock,
)
from text_verification.domain.jobs import JobProgressStage, JobRead
from text_verification.domain.ports import AnchoredSourcePathResolver
from text_verification.domain.text_edits import (
    MAX_REVISION_TEXT_CODEPOINTS,
    MAX_REVISION_TEXT_UTF8_BYTES,
    MAX_TEXT_DIFF_WORK,
    MAX_TEXT_EDIT_OPERATIONS,
    CheckedTextWorkBudget,
    TextDiffLimitError,
    validate_revision_text,
)
from text_verification.domain.verification import (
    PersistedDocumentRevision,
    RecheckProvenance,
    StaleReviewRevisionError,
    VerificationResult,
)
from text_verification.exporters.compatibility_exporter import CompatibilityExporter
from text_verification.exporters.docx_reconstruction import DocxReconstructionExporter
from text_verification.exporters.registry import ExporterRegistry
from text_verification.infrastructure.artifact_storage import (
    ArtifactNotFoundError,
    ArtifactRepairPreparation,
    ArtifactRepairQuarantine,
    ArtifactRepairState,
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
MEDIA_TYPES = {
    FileType.CSV: "text/csv",
    FileType.DOC: "application/msword",
    FileType.DOCX: DOCX_MEDIA_TYPE,
    FileType.MARKDOWN: "text/markdown",
    FileType.PDF: "application/pdf",
    FileType.RTF: "application/rtf",
    FileType.TXT: "text/plain",
}
MAX_REVISION_PROJECTION_BLOCKS = 20_000
MAX_REVISION_PROJECTION_TOTAL_CODEPOINTS = 3 * MAX_REVISION_TEXT_CODEPOINTS
MAX_REVISION_PROJECTION_TOTAL_UTF8_BYTES = 3 * MAX_REVISION_TEXT_UTF8_BYTES
ExportProgressObserver = Callable[[JobProgressStage], None]
ExporterRegistryFactory = Callable[[AnchoredSourcePathResolver], ExporterRegistry]


class ReconstructionRepository(ArtifactRepository, Protocol):
    def read_result_snapshot(self, job_id: UUID) -> JobResultSnapshot: ...

    def read_review_revision(
        self,
        review_revision_id: UUID,
    ) -> PersistedDocumentRevision | None: ...

    def read_export_revision(
        self,
        job_id: UUID,
        verification_run_id: UUID,
        review_revision_id: UUID | None,
    ) -> PersistedDocumentRevision | None: ...

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


@dataclass(frozen=True)
class _PreparedRepair:
    reservation: ArtifactReservation
    quarantine: ArtifactRepairQuarantine | None


class ReconstructionExportService:
    def __init__(
        self,
        storage: JobStorage,
        repository_factory: ReconstructionRepositoryFactory,
        *,
        exporter_registry_factory: ExporterRegistryFactory,
        now_factory: Callable[[], datetime] | None = None,
        max_revision_bytes: int | None = None,
        max_revision_codepoints: int = MAX_REVISION_TEXT_CODEPOINTS,
        recheck_grant_service: RecheckProvenanceGrantService | None = None,
    ) -> None:
        self._storage = storage
        self._repository_factory = repository_factory
        self._exporter_registry_factory = exporter_registry_factory
        self._now_factory = now_factory or (lambda: datetime.now(UTC))
        self._max_revision_bytes = (
            storage.max_document_bytes
            if max_revision_bytes is None
            else max_revision_bytes
        )
        self._max_revision_bytes = min(
            self._max_revision_bytes,
            MAX_REVISION_TEXT_UTF8_BYTES,
        )
        self._max_revision_codepoints = min(
            max_revision_codepoints,
            MAX_REVISION_TEXT_CODEPOINTS,
        )
        self._recheck_grant_service = recheck_grant_service

    def export(
        self,
        job: JobRead,
        export_format: ExportFormat,
        *,
        review_revision_id: UUID | None = None,
        track_changes: bool = False,
        recheck_provenance: RecheckProvenance | None = None,
        progress_observer: ExportProgressObserver | None = None,
    ) -> ExportArtifactReference:
        if export_format not in {
            ExportFormat.DOCX_RECONSTRUCTION,
            ExportFormat.ORIGINAL_FORMAT,
        }:
            raise VerificationError(
                "unsupported_export_format",
                "exporting",
                "The requested export format is not supported.",
                False,
            )
        result = self._load_result(job.job_id)
        document = _document_from_result(result)
        revision = self._load_export_revision(
            job.job_id,
            result,
            review_revision_id,
        )
        if revision is not None:
            _validate_revision_identity(revision, result)
            self._validate_revision_text(revision.text)
        if recheck_provenance is not None:
            self._verify_recheck_provenance(
                job.job_id,
                result,
                recheck_provenance,
            )
        if export_format is ExportFormat.DOCX_RECONSTRUCTION:
            if revision is not None:
                document = _document_with_revision_text(document, revision.text)
            _validate_reconstruction_eligibility(document)
            output_file_type = FileType.DOCX
            file_name = _reconstruction_file_name(job.source_name)
        else:
            output_file_type = document.file_type
            file_name = _original_format_file_name(
                job.source_name,
                output_file_type,
            )

        artifact_id = _artifact_id(
            job,
            result.verification_run_id,
            export_format,
            review_revision_id,
            track_changes,
        )
        media_type = MEDIA_TYPES[output_file_type]
        storage_key = build_artifact_storage_key(
            job.job_id,
            artifact_id,
            output_file_type,
        )
        existing = self._read_artifact(artifact_id)
        repair_candidate = existing is not None
        if existing is not None and existing.status is ArtifactLifecycleStatus.READY:
            reference = _reference_from_snapshot(
                existing,
                job=job,
                verification_run_id=result.verification_run_id,
                review_revision_id=review_revision_id,
                export_format=export_format,
                file_type=output_file_type,
                file_name=file_name,
                media_type=media_type,
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
                self._assert_current_result(job.job_id, result)
                self._load_export_revision(
                    job.job_id,
                    result,
                    review_revision_id,
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
        exporter = registry.get(
            ExportFormat.DOCX_RECONSTRUCTION
            if export_format is ExportFormat.DOCX_RECONSTRUCTION
            else document.file_type
        )
        work_path = (
            self._storage.job_directory(job.job_id)
            / (
                f".{uuid4().hex}.reconstructing.docx"
                if export_format is ExportFormat.DOCX_RECONSTRUCTION
                else f".{uuid4().hex}.exporting.{output_file_type.value}"
            )
        )
        try:
            try:
                if export_format is ExportFormat.DOCX_RECONSTRUCTION:
                    cast(DocxReconstructionExporter, exporter).export(
                        document,
                        work_path,
                    )
                else:
                    cast(CompatibilityExporter, exporter).export(
                        document,
                        [],
                        work_path,
                        track_changes=track_changes,
                        modified_text=(
                            revision.text if revision is not None else document.text
                        ),
                    )
                data = work_path.read_bytes()
            except (ExportError, OSError, ValueError) as error:
                raise VerificationError(
                    (
                        "document_reconstruction_failed"
                        if export_format is ExportFormat.DOCX_RECONSTRUCTION
                        else "original_format_export_failed"
                    ),
                    "exporting",
                    (
                        "The canonical document could not be reconstructed."
                        if export_format is ExportFormat.DOCX_RECONSTRUCTION
                        else "The job-owned source document could not be exported."
                    ),
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
            review_revision_id=review_revision_id,
            source_version=result.source_version,
            file_type=output_file_type,
            file_name=file_name,
            media_type=media_type,
            storage_key=storage_key,
            data=data,
            created_at=job.created_at,
        )
        self._assert_current_result(job.job_id, result)
        prepared_repair = (
            self._begin_repair(request)
            if repair_candidate
            else None
        )
        if progress_observer is not None:
            progress_observer(JobProgressStage.FINALIZING)
        try:
            persisted = ArtifactPersistenceService(
                self._storage,
                cast(ArtifactRepositoryFactory, self._repository_factory),
                require_current_result=True,
            ).persist(
                request,
                reservation=(
                    prepared_repair.reservation
                    if prepared_repair is not None
                    else None
                ),
            )
        except ArtifactFinalizationRejectedError as error:
            if error.reason is ArtifactFinalizationRejection.STALE_REVISION:
                if (
                    prepared_repair is not None
                    and prepared_repair.quarantine is not None
                ):
                    self._delete_repair_quarantine(
                        prepared_repair.quarantine,
                    )
                raise VerificationError(
                    "revision_export_stale",
                    "finalizing",
                    "The requested revision is no longer the latest persisted revision.",
                    False,
                ) from error
            raise VerificationError(
                "job_result_expired",
                "finalizing",
                "Job result has expired.",
                False,
            ) from error
        except StaleReviewRevisionError as error:
            raise VerificationError(
                "revision_export_stale",
                "finalizing",
                "The requested revision is no longer the latest persisted revision.",
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
        if (
            prepared_repair is not None
            and prepared_repair.quarantine is not None
        ):
            self._delete_repair_quarantine(prepared_repair.quarantine)
        return ExportArtifactReference(
            export_artifact_id=persisted.export_artifact_id,
            job_id=persisted.job_id,
            verification_run_id=result.verification_run_id,
            format=export_format,
            file_type=persisted.file_type,
            file_name=file_name,
            media_type=media_type,
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
                artifact = repository.read_export_artifact(export_artifact_id)
                if artifact is None or artifact.job_id != job_id:
                    raise VerificationError(
                        "export_artifact_not_found",
                        "exporting",
                        "The export artifact was not found.",
                        False,
                    )
                try:
                    revision = repository.read_export_revision(
                        job_id,
                        artifact.verification_run_id,
                        artifact.review_revision_id,
                    )
                except StaleReviewRevisionError as error:
                    raise VerificationError(
                        "revision_export_stale",
                        "exporting",
                        "The requested revision is no longer the latest persisted revision.",
                        False,
                    ) from error
                except (LookupError, ValueError) as error:
                    raise VerificationError(
                        "export_artifact_not_found",
                        "exporting",
                        "The export artifact was not found.",
                        False,
                    ) from error
                result_snapshot = repository.read_result_snapshot(job_id)
                result = self._download_result(result_snapshot)
                if artifact is None or not _artifact_belongs_to_result(
                    artifact,
                    job_id,
                    result,
                    revision,
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
                if (
                    result.file_type is FileType.PDF
                    and artifact.file_type is FileType.DOCX
                ):
                    _validate_reconstruction_eligibility(
                        _document_from_result(result)
                    )
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

    def _validate_revision_text(self, text: str) -> None:
        try:
            validate_revision_text(
                text,
                max_codepoints=self._max_revision_codepoints,
                max_utf8_bytes=self._max_revision_bytes,
            )
        except TextDiffLimitError as error:
            raise VerificationError(
                "revision_text_too_large",
                "exporting",
                "The persisted revision exceeds the configured size limit.",
                False,
            ) from error

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

    def _verify_recheck_provenance(
        self,
        job_id: UUID,
        result: VerificationResult,
        provenance: RecheckProvenance,
    ) -> None:
        if self._recheck_grant_service is None:
            raise VerificationError(
                "recheck_provenance_unavailable",
                "exporting",
                "Secure recheck provenance is not configured.",
                True,
            )
        try:
            self._recheck_grant_service.verify(
                provenance.grant,
                RecheckGrantBinding(
                    job_id=job_id,
                    original_document_id=result.document_id,
                    original_verification_run_id=result.verification_run_id,
                    original_source_version=result.source_version,
                    submitted_text=provenance.recheck_text,
                    result_document_id=provenance.result_document_id,
                    result_verification_run_id=(
                        provenance.result_verification_run_id
                    ),
                    result_source_version=provenance.result_source_version,
                ),
            )
        except RecheckGrantError as error:
            raise VerificationError(
                "recheck_provenance_invalid",
                "exporting",
                "The recheck provenance grant is invalid or expired.",
                False,
            ) from error

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

    def _load_export_revision(
        self,
        job_id: UUID,
        result: VerificationResult,
        review_revision_id: UUID | None,
    ) -> PersistedDocumentRevision | None:
        with self._repository_factory() as repository:
            try:
                revision = repository.read_export_revision(
                    job_id,
                    result.verification_run_id,
                    review_revision_id,
                )
            except StaleReviewRevisionError as error:
                raise VerificationError(
                    "revision_export_stale",
                    "exporting",
                    "The requested revision is no longer the latest persisted revision.",
                    False,
                ) from error
            except LookupError as error:
                raise VerificationError(
                    "revision_not_found",
                    "exporting",
                    "The requested persisted revision was not found.",
                    False,
                ) from error
            except ValueError as error:
                raise VerificationError(
                    "revision_identity_mismatch",
                    "exporting",
                    "The requested revision does not belong to this verification result.",
                    False,
                ) from error
            finally:
                repository.rollback()
        return revision

    def _read_artifact(self, export_artifact_id: UUID) -> ArtifactSnapshot | None:
        with self._repository_factory() as repository:
            try:
                return repository.read_export_artifact(export_artifact_id)
            finally:
                repository.rollback()

    def _begin_repair(
        self,
        request: ArtifactPersistenceRequest,
    ) -> _PreparedRepair:
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
        preparation: ArtifactRepairPreparation | None = None

        def prepare_repair() -> ArtifactRepairPreparation | None:
            nonlocal preparation
            preparation = self._storage.prepare_artifact_repair(
                request.job_id,
                request.export_artifact_id,
                request.storage_key,
                request.file_type,
                expected_size=len(request.data),
                expected_digest=digest,
            )
            return preparation

        with self._repository_factory() as repository:
            try:
                reservation = repository.begin_export_artifact_repair(
                    expected,
                    consistency_check=prepare_repair,
                )
                if reservation is None:
                    raise ValueError("Artifact repair candidate no longer exists.")
                repository.commit()
                return _PreparedRepair(
                    reservation=reservation,
                    quarantine=(
                        preparation.quarantine
                        if preparation is not None
                        and preparation.state
                        in {
                            ArtifactRepairState.QUARANTINED,
                            ArtifactRepairState.REUSED_QUARANTINE,
                        }
                        else None
                    ),
                )
            except StaleReviewRevisionError as error:
                repository.rollback()
                raise VerificationError(
                    "revision_export_stale",
                    "finalizing",
                    "The requested revision is no longer the latest persisted revision.",
                    False,
                ) from error
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
        quarantine: ArtifactRepairQuarantine,
    ) -> None:
        try:
            self._storage.delete_artifact_repair_quarantine(quarantine)
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


def _validate_revision_identity(
    revision: PersistedDocumentRevision,
    result: VerificationResult,
) -> None:
    if (
        revision.verification_run_id != result.verification_run_id
        or revision.document_id != result.document_id
        or revision.source_version != result.source_version
    ):
        raise VerificationError(
            "revision_identity_mismatch",
            "exporting",
            "The requested revision does not belong to this verification result.",
            False,
        )


def _preflight_revision_projection(
    document: DocumentModel,
    revised_text: str,
) -> None:
    if len(document.blocks) > MAX_REVISION_PROJECTION_BLOCKS:
        raise _revision_diff_too_complex()
    try:
        validate_revision_text(
            document.text,
            max_codepoints=MAX_REVISION_TEXT_CODEPOINTS,
            max_utf8_bytes=MAX_REVISION_TEXT_UTF8_BYTES,
        )
        validate_revision_text(
            revised_text,
            max_codepoints=MAX_REVISION_TEXT_CODEPOINTS,
            max_utf8_bytes=MAX_REVISION_TEXT_UTF8_BYTES,
        )
        total_codepoints = len(document.text) + len(revised_text)
        total_utf8_bytes = len(document.text.encode("utf-8")) + len(
            revised_text.encode("utf-8")
        )
        for block in document.blocks:
            total_codepoints += len(block.text)
            total_utf8_bytes += len(block.text.encode("utf-8"))
            if (
                total_codepoints > MAX_REVISION_PROJECTION_TOTAL_CODEPOINTS
                or total_utf8_bytes > MAX_REVISION_PROJECTION_TOTAL_UTF8_BYTES
            ):
                raise TextDiffLimitError(
                    "Revision projection text exceeds the total text limit."
                )
    except (TextDiffLimitError, UnicodeEncodeError) as error:
        raise VerificationError(
            "revision_text_too_large",
            "exporting",
            "The persisted revision exceeds the configured size limit.",
            False,
        ) from error


def _document_with_revision_text(
    document: DocumentModel,
    revised_text: str,
) -> DocumentModel:
    if revised_text == document.text:
        return document
    _preflight_revision_projection(document, revised_text)
    if not document.blocks:
        raise VerificationError(
            "revision_text_unmappable",
            "exporting",
            "The persisted revision cannot be mapped to canonical document blocks.",
            False,
        )
    budget = CheckedTextWorkBudget(
        MAX_TEXT_DIFF_WORK,
        MAX_TEXT_EDIT_OPERATIONS,
    )
    try:
        budget.charge_work(len(document.blocks))
    except TextDiffLimitError as error:
        raise _revision_diff_too_complex() from error
    block_index_by_id = {
        block.block_id: index for index, block in enumerate(document.blocks)
    }
    children_by_id: dict[str, list[int]] = {}
    for index, block in enumerate(document.blocks):
        if block.parent_id is not None:
            children_by_id.setdefault(block.parent_id, []).append(index)
    text_kinds = {"paragraph", "heading", "table_cell"}
    renderable_ancestor_by_id: dict[str, bool] = {}
    try:
        for block in document.blocks:
            if block.kind not in text_kinds:
                continue
            parent_id = block.parent_id
            path: list[str] = []
            has_renderable_ancestor = False
            while parent_id is not None:
                budget.charge_work(1)
                cached = renderable_ancestor_by_id.get(parent_id)
                if cached is not None:
                    has_renderable_ancestor = cached
                    break
                parent = document.blocks[block_index_by_id[parent_id]]
                path.append(parent_id)
                if parent.kind in text_kinds:
                    has_renderable_ancestor = True
                    break
                parent_id = parent.parent_id
            for ancestor_id in path:
                renderable_ancestor_by_id[ancestor_id] = has_renderable_ancestor
            if has_renderable_ancestor:
                raise VerificationError(
                    "revision_text_unmappable",
                    "exporting",
                    "The persisted revision cannot be mapped to canonical document blocks.",
                    False,
                )
    except TextDiffLimitError as error:
        raise _revision_diff_too_complex() from error
    owner_indexes = [
        index
        for index, block in enumerate(document.blocks)
        if block.kind in text_kinds
        and not any(
            document.blocks[child_index].kind in text_kinds
            for child_index in children_by_id.get(block.block_id, [])
        )
    ]
    if not owner_indexes:
        raise VerificationError(
            "revision_text_unmappable",
            "exporting",
            "The persisted revision cannot be mapped to canonical document blocks.",
            False,
        )
    try:
        budget.charge_work(
            len(owner_indexes) * max(1, len(owner_indexes).bit_length())
        )
    except TextDiffLimitError as error:
        raise _revision_diff_too_complex() from error
    owner_indexes.sort(
        key=lambda index: (
            document.blocks[index].global_start,
            document.blocks[index].global_end,
            document.blocks[index].block_id,
        )
    )
    for left_index, right_index in zip(
        owner_indexes[:-1],
        owner_indexes[1:],
        strict=True,
    ):
        left = document.blocks[left_index]
        right = document.blocks[right_index]
        if left.global_end > right.global_start:
            raise _revision_structure_conflict()
    try:
        budget.charge_work(max(0, len(owner_indexes) - 1))
        owner_text = _project_revision_owner_text(
            document.text,
            revised_text,
            owner_indexes,
            document.blocks,
            budget,
        )
        budget.charge_work(
            len(document.text) + len(revised_text) + len(owner_indexes)
        )
    except TextDiffLimitError as error:
        raise _revision_diff_too_complex() from error

    ranges: list[list[int] | None] = [None] * len(document.blocks)

    anchored_ranges: list[tuple[int, int, int, int]] = []
    rebuilt_parts: list[str] = []
    source_cursor = 0
    target_cursor = 0
    for owner_index in owner_indexes:
        block = document.blocks[owner_index]
        structural_text = document.text[source_cursor:block.global_start]
        rebuilt_parts.append(structural_text)
        structural_end = target_cursor + len(structural_text)
        anchored_ranges.append(
            (
                source_cursor,
                block.global_start,
                target_cursor,
                structural_end,
            )
        )
        target_cursor = structural_end

        block_text = owner_text[owner_index]
        start = target_cursor
        end = start + len(block_text)
        ranges[owner_index] = [start, end]
        rebuilt_parts.append(block_text)
        target_cursor = end
        source_cursor = block.global_end

    structural_text = document.text[source_cursor:]
    rebuilt_parts.append(structural_text)
    anchored_ranges.append(
        (
            source_cursor,
            len(document.text),
            target_cursor,
            target_cursor + len(structural_text),
        )
    )
    if "".join(rebuilt_parts) != revised_text:
        raise _revision_structure_conflict()

    anchored_starts = [source_start for source_start, _, _, _ in anchored_ranges]
    for index, block in enumerate(document.blocks):
        if ranges[index] is not None:
            continue
        try:
            budget.charge_work(1)
        except TextDiffLimitError as error:
            raise _revision_diff_too_complex() from error
        anchor_index = bisect_right(anchored_starts, block.global_start) - 1
        if anchor_index < 0:
            continue
        source_start, source_end, target_start, _ = anchored_ranges[anchor_index]
        if block.global_end <= source_end:
            ranges[index] = [
                target_start + block.global_start - source_start,
                target_start + block.global_end - source_start,
            ]

    try:
        depths = _block_depths(
            document.blocks,
            block_index_by_id,
            budget,
        )
        budget.charge_work(
            len(document.blocks) * max(1, len(document.blocks).bit_length())
        )
    except TextDiffLimitError as error:
        raise _revision_diff_too_complex() from error
    for index in sorted(
        range(len(document.blocks)),
        key=lambda candidate: depths[document.blocks[candidate].block_id],
        reverse=True,
    ):
        parent_id = document.blocks[index].parent_id
        if parent_id is None:
            continue
        parent_index = block_index_by_id[parent_id]
        child_range = ranges[index]
        if child_range is None:
            raise _revision_structure_conflict()
        parent_range = ranges[parent_index]
        if parent_range is None:
            ranges[parent_index] = list(child_range)
        else:
            parent_range[0] = min(parent_range[0], child_range[0])
            parent_range[1] = max(parent_range[1], child_range[1])

    try:
        budget.charge_work(len(document.blocks))
    except TextDiffLimitError as error:
        raise _revision_diff_too_complex() from error
    blocks = []
    for block, mapped_range in zip(document.blocks, ranges, strict=True):
        if mapped_range is None:
            raise _revision_structure_conflict()
        start, end = mapped_range
        if end < start:
            raise _revision_structure_conflict()
        text = revised_text[start:end]
        style = dict(block.style)
        if text != block.text:
            style.pop("spans", None)
        blocks.append(
            block.model_copy(
                update={
                    "text": text,
                    "global_start": start,
                    "global_end": end,
                    "block_start": 0,
                    "block_end": len(text),
                    "style": style,
                }
            )
        )
    try:
        return document.model_copy(
            update={"text": revised_text, "blocks": blocks}
        ).model_validate(
            {
                **document.model_dump(),
                "text": revised_text,
                "blocks": [block.model_dump() for block in blocks],
            }
        )
    except ValueError as error:
        raise _revision_structure_conflict() from error


def _project_revision_owner_text(
    source_text: str,
    revised_text: str,
    owner_indexes: list[int],
    blocks: list[TextBlock],
    budget: CheckedTextWorkBudget,
) -> dict[int, str]:
    owner_starts = [blocks[index].global_start for index in owner_indexes]
    owner_ends = [blocks[index].global_end for index in owner_indexes]

    def owner_at(position: int) -> int | None:
        budget.charge_work(1)
        candidate = bisect_right(owner_starts, position) - 1
        if candidate < 0 or position >= owner_ends[candidate]:
            return None
        return owner_indexes[candidate]

    def insertion_owner(boundary: int) -> int | None:
        if boundary > 0:
            left = owner_at(boundary - 1)
            if left is not None:
                return left
        if boundary < len(source_text):
            return owner_at(boundary)
        return None

    prefix_length = _common_prefix_length(
        source_text,
        revised_text,
        budget,
    )
    suffix_length = _common_suffix_length(
        source_text,
        revised_text,
        prefix_length,
        budget,
    )
    source_end = len(source_text) - suffix_length
    revised_end = len(revised_text) - suffix_length
    source_middle = source_text[prefix_length:source_end]
    revised_middle = revised_text[prefix_length:revised_end]
    work = (
        len(source_middle) * len(revised_middle)
        if source_middle and revised_middle
        else max(len(source_middle), len(revised_middle))
    )
    budget.charge_work(work)

    width = len(revised_middle) + 1
    directions = bytearray((len(source_middle) + 1) * width)
    unreachable = work + len(source_middle) + len(revised_middle) + 1
    previous = [unreachable] * width
    previous[0] = 0
    first_insertion_owner = insertion_owner(prefix_length)
    if first_insertion_owner is not None:
        for revised_index in range(1, width):
            previous[revised_index] = revised_index
            directions[revised_index] = 3

    for source_index, source_character in enumerate(source_middle, start=1):
        source_position = prefix_length + source_index - 1
        source_owner = owner_at(source_position)
        current = [unreachable] * width
        row_offset = source_index * width
        if source_owner is not None and previous[0] < unreachable:
            current[0] = previous[0] + 1
            directions[row_offset] = 2
        boundary_owner = insertion_owner(source_position + 1)
        for revised_index, revised_character in enumerate(
            revised_middle,
            start=1,
        ):
            best_cost = unreachable
            best_priority = 4
            best_direction = 0

            if previous[revised_index - 1] < unreachable and (
                source_owner is not None
                or source_character == revised_character
            ):
                substitution = int(source_character != revised_character)
                best_cost = previous[revised_index - 1] + substitution
                best_priority = substitution
                best_direction = 1

            if source_owner is not None and previous[revised_index] < unreachable:
                deletion_cost = previous[revised_index] + 1
                if (deletion_cost, 2) < (best_cost, best_priority):
                    best_cost = deletion_cost
                    best_priority = 2
                    best_direction = 2

            if boundary_owner is not None and current[revised_index - 1] < unreachable:
                insertion_cost = current[revised_index - 1] + 1
                if (insertion_cost, 3) < (best_cost, best_priority):
                    best_cost = insertion_cost
                    best_priority = 3
                    best_direction = 3

            current[revised_index] = best_cost
            directions[row_offset + revised_index] = best_direction
        previous = current

    if previous[-1] >= unreachable:
        raise _revision_structure_conflict()

    source_index = len(source_middle)
    revised_index = len(revised_middle)
    middle_owners: list[int | None] = []
    edit_steps: list[tuple[str | None, int | None]] = []
    while source_index > 0 or revised_index > 0:
        direction = directions[source_index * width + revised_index]
        if direction == 1:
            source_position = prefix_length + source_index - 1
            owner = owner_at(source_position)
            changed = (
                source_middle[source_index - 1]
                != revised_middle[revised_index - 1]
            )
            middle_owners.append(owner)
            edit_steps.append(("replace" if changed else None, owner))
            source_index -= 1
            revised_index -= 1
        elif direction == 2:
            source_position = prefix_length + source_index - 1
            owner = owner_at(source_position)
            edit_steps.append(("delete", owner))
            source_index -= 1
        elif direction == 3:
            owner = insertion_owner(prefix_length + source_index)
            middle_owners.append(owner)
            edit_steps.append(("insert", owner))
            revised_index -= 1
        else:
            raise _revision_structure_conflict()

    previous_edit_owner: int | None = None
    previous_was_edit = False
    for operation, owner in reversed(edit_steps):
        is_edit = operation is not None
        if is_edit and (
            not previous_was_edit
            or owner is None
            or owner != previous_edit_owner
        ):
            budget.charge_operation()
        previous_was_edit = is_edit
        previous_edit_owner = owner if is_edit else None

    budget.charge_work(
        prefix_length
        + suffix_length
        + len(middle_owners)
        + len(revised_text)
    )
    target_owners = [
        owner_at(position)
        for position in range(prefix_length)
    ]
    target_owners.extend(reversed(middle_owners))
    target_owners.extend(
        owner_at(position)
        for position in range(source_end, len(source_text))
    )
    if len(target_owners) != len(revised_text):
        raise _revision_structure_conflict()

    owner_parts: dict[int, list[str]] = {
        index: [] for index in owner_indexes
    }
    for character, owner in zip(revised_text, target_owners, strict=True):
        if owner is not None:
            owner_parts[owner].append(character)
    return {
        owner_index: "".join(owner_parts[owner_index])
        for owner_index in owner_indexes
    }


def _common_prefix_length(
    left: str,
    right: str,
    budget: CheckedTextWorkBudget,
) -> int:
    limit = min(len(left), len(right))
    index = 0
    while index < limit:
        budget.charge_work(1)
        if left[index] != right[index]:
            break
        index += 1
    return index


def _common_suffix_length(
    left: str,
    right: str,
    prefix_length: int,
    budget: CheckedTextWorkBudget,
) -> int:
    limit = min(len(left), len(right)) - prefix_length
    count = 0
    while count < limit:
        budget.charge_work(1)
        if left[-count - 1] != right[-count - 1]:
            break
        count += 1
    return count


def _revision_structure_conflict() -> VerificationError:
    return VerificationError(
        "revision_structure_conflict",
        "exporting",
        "The persisted revision changes or ambiguously crosses a document structure boundary.",
        False,
    )


def _revision_diff_too_complex() -> VerificationError:
    return VerificationError(
        "revision_diff_too_complex",
        "exporting",
        "The persisted revision exceeds the configured edit work budget.",
        False,
    )


def _block_depths(
    blocks: list[TextBlock],
    block_index_by_id: dict[str, int],
    budget: CheckedTextWorkBudget,
) -> dict[str, int]:
    depths: dict[str, int] = {}
    for block in blocks:
        if block.block_id in depths:
            continue
        path: list[str] = []
        current_id = block.block_id
        while current_id not in depths:
            budget.charge_work(1)
            path.append(current_id)
            parent_id = blocks[block_index_by_id[current_id]].parent_id
            if parent_id is None:
                break
            current_id = parent_id
        for block_id in reversed(path):
            parent_id = blocks[block_index_by_id[block_id]].parent_id
            depths[block_id] = (
                0
                if parent_id is None
                else depths[parent_id] + 1
            )
    return depths


def _uncovered_ranges(
    start: int,
    end: int,
    ranges: list[list[int]],
) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for range_start, range_end in sorted(
        (
            (max(start, range_start), min(end, range_end))
            for range_start, range_end in ranges
            if range_start < end and start < range_end
        )
    ):
        if not merged or range_start > merged[-1][1]:
            merged.append((range_start, range_end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], range_end))
    uncovered: list[tuple[int, int]] = []
    cursor = start
    for range_start, range_end in merged:
        if cursor < range_start:
            uncovered.append((cursor, range_start))
        cursor = max(cursor, range_end)
    if cursor < end:
        uncovered.append((cursor, end))
    return uncovered


def _range_distance(
    range_start: int,
    range_end: int,
    target_start: int,
    target_end: int,
) -> int:
    if range_end <= target_start:
        return target_start - range_end
    if target_end <= range_start:
        return range_start - target_end
    return 0


def _covered_length(ranges: list[tuple[int, int]]) -> int:
    total = 0
    current_start: int | None = None
    current_end = 0
    for start, end in sorted(ranges):
        if current_start is None or start > current_end:
            if current_start is not None:
                total += current_end - current_start
            current_start = start
            current_end = end
        else:
            current_end = max(current_end, end)
    if current_start is not None:
        total += current_end - current_start
    return total


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
    review_revision_id: UUID | None = None,
    track_changes: bool = False,
) -> UUID:
    revision_key = (
        ""
        if review_revision_id is None
        else f"{review_revision_id}:"
    )
    return uuid5(
        NAMESPACE_URL,
        (
            f"export:{job.job_id}:{verification_run_id}:"
            f"{revision_key}{export_format.value}:{int(track_changes)}:"
            f"{job.created_at.isoformat()}"
        ),
    )


def _reconstruction_file_name(source_name: str) -> str:
    stem = Path(source_name).stem.replace("\r", "").replace("\n", "").strip()
    return f"{stem or 'document'}-reconstructed.docx"


def _original_format_file_name(
    source_name: str,
    file_type: FileType,
) -> str:
    stem = Path(source_name).stem.replace("\r", "").replace("\n", "").strip()
    return f"{stem or 'document'}-modified.{file_type.value}"


def _reference_from_snapshot(
    snapshot: ArtifactSnapshot,
    *,
    job: JobRead,
    verification_run_id: UUID,
    review_revision_id: UUID | None,
    export_format: ExportFormat,
    file_type: FileType,
    file_name: str,
    media_type: str,
    storage_key: str,
) -> ExportArtifactReference:
    expected = (
        job.job_id,
        verification_run_id,
        review_revision_id,
        file_type,
        file_name,
        media_type,
        storage_key,
        job.created_at,
    )
    actual = (
        snapshot.job_id,
        snapshot.verification_run_id,
        snapshot.review_revision_id,
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
    revision: PersistedDocumentRevision | None,
) -> bool:
    return (
        artifact.job_id == job_id
        and artifact.verification_run_id == result.verification_run_id
        and artifact.source_version == result.source_version
        and artifact.file_type in {FileType.DOCX, result.file_type}
        and (
            (
                artifact.review_revision_id is None
                and revision is None
            )
            or (
                artifact.review_revision_id is not None
                and revision is not None
                and revision.revision_id == artifact.review_revision_id
                and revision.verification_run_id == result.verification_run_id
                and revision.document_id == result.document_id
                and revision.source_version == result.source_version
            )
        )
    )
