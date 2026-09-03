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
    BoundedTextEdit,
    TextDiffLimitError,
    build_bounded_text_edits,
    validate_revision_text,
)
from text_verification.domain.verification import (
    PersistedDocumentRevision,
    StaleReviewRevisionError,
    VerificationResult,
)
from text_verification.exporters.compatibility_exporter import CompatibilityExporter
from text_verification.exporters.docx_reconstruction import DocxReconstructionExporter
from text_verification.exporters.registry import ExporterRegistry
from text_verification.infrastructure.artifact_storage import (
    ArtifactNotFoundError,
    ArtifactRepairPreparation,
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
    quarantine_owned: bool


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

    def export(
        self,
        job: JobRead,
        export_format: ExportFormat,
        *,
        review_revision_id: UUID | None = None,
        track_changes: bool = False,
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
                self._delete_repair_quarantine(
                    existing.job_id,
                    existing.export_artifact_id,
                    existing.storage_key,
                    existing.file_type,
                )
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
                    and prepared_repair.quarantine_owned
                ):
                    self._delete_repair_quarantine(
                        request.job_id,
                        request.export_artifact_id,
                        request.storage_key,
                        request.file_type,
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
                    quarantine_owned=(
                        preparation is ArtifactRepairPreparation.QUARANTINED
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


def _document_with_revision_text(
    document: DocumentModel,
    revised_text: str,
) -> DocumentModel:
    if revised_text == document.text:
        return document
    if not document.blocks:
        raise VerificationError(
            "revision_text_unmappable",
            "exporting",
            "The persisted revision cannot be mapped to canonical document blocks.",
            False,
        )
    block_index_by_id = {
        block.block_id: index for index, block in enumerate(document.blocks)
    }
    children_by_id: dict[str, list[int]] = {}
    for index, block in enumerate(document.blocks):
        if block.parent_id is not None:
            children_by_id.setdefault(block.parent_id, []).append(index)
    text_kinds = {"paragraph", "heading", "table_cell"}
    for block in document.blocks:
        if block.kind not in text_kinds:
            continue
        parent_id = block.parent_id
        while parent_id is not None:
            parent = document.blocks[block_index_by_id[parent_id]]
            if parent.kind in text_kinds:
                raise VerificationError(
                    "revision_text_unmappable",
                    "exporting",
                    "The persisted revision cannot be mapped to canonical document blocks.",
                    False,
                )
            parent_id = parent.parent_id
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

    ranges: list[list[int] | None] = [None] * len(document.blocks)
    try:
        edits = build_bounded_text_edits(
            document.text,
            revised_text,
            max_work=MAX_TEXT_DIFF_WORK,
            max_operations=MAX_TEXT_EDIT_OPERATIONS,
        )
    except TextDiffLimitError as error:
        raise VerificationError(
            "revision_diff_too_complex",
            "exporting",
            "The persisted revision exceeds the configured edit work budget.",
            False,
        ) from error

    owner_edits: dict[int, list[BoundedTextEdit]] = {
        owner_index: [] for owner_index in owner_indexes
    }
    for edit in edits:
        owner_index = _edit_owner(edit, owner_indexes, document.blocks)
        if owner_index is None:
            raise _revision_structure_conflict()
        block = document.blocks[owner_index]
        owner_edits[owner_index].append(
            BoundedTextEdit(
                edit.start - block.global_start,
                edit.end - block.global_start,
                edit.replacement,
            )
        )

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

        block_text = _apply_bounded_text_edits(
            block.text,
            owner_edits[owner_index],
        )
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

    for index, block in enumerate(document.blocks):
        if ranges[index] is not None:
            continue
        for source_start, source_end, target_start, _ in anchored_ranges:
            if (
                source_start <= block.global_start
                and block.global_end <= source_end
            ):
                ranges[index] = [
                    target_start + block.global_start - source_start,
                    target_start + block.global_end - source_start,
                ]
                break

    depths = {
        block.block_id: _block_depth(block, document.blocks, block_index_by_id)
        for block in document.blocks
    }
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


def _edit_owner(
    edit: BoundedTextEdit,
    owner_indexes: list[int],
    blocks: list[TextBlock],
) -> int | None:
    if edit.start < edit.end:
        owners = [
            owner_index
            for owner_index in owner_indexes
            if (
                blocks[owner_index].global_start <= edit.start
                and edit.end <= blocks[owner_index].global_end
            )
        ]
        return owners[0] if len(owners) == 1 else None

    containing_owners = [
        owner_index
        for owner_index in owner_indexes
        if (
            blocks[owner_index].global_start < edit.start
            < blocks[owner_index].global_end
        )
    ]
    if len(containing_owners) == 1:
        return containing_owners[0]
    if containing_owners:
        return None
    ending_owner = next(
        (
            owner_index
            for owner_index in reversed(owner_indexes)
            if blocks[owner_index].global_end == edit.start
        ),
        None,
    )
    if ending_owner is not None:
        return ending_owner
    return next(
        (
            owner_index
            for owner_index in owner_indexes
            if blocks[owner_index].global_start == edit.start
        ),
        None,
    )


def _apply_bounded_text_edits(
    text: str,
    edits: list[BoundedTextEdit],
) -> str:
    revised = text
    for edit in reversed(edits):
        revised = (
            f"{revised[:edit.start]}"
            f"{edit.replacement}"
            f"{revised[edit.end:]}"
        )
    return revised


def _revision_structure_conflict() -> VerificationError:
    return VerificationError(
        "revision_structure_conflict",
        "exporting",
        "The persisted revision changes or ambiguously crosses a document structure boundary.",
        False,
    )


def _block_depth(
    block: TextBlock,
    blocks: list[TextBlock],
    block_index_by_id: dict[str, int],
) -> int:
    depth = 0
    parent_id = block.parent_id
    while parent_id is not None:
        depth += 1
        parent = blocks[block_index_by_id[parent_id]]
        parent_id = parent.parent_id
    return depth


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
