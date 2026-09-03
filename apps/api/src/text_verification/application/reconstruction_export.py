from __future__ import annotations

import hashlib
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
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
        if revision is not None:
            _validate_revision_identity(revision, result)

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
            if error.reason is ArtifactFinalizationRejection.STALE_REVISION:
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
    opcodes = SequenceMatcher(
        None,
        document.text,
        revised_text,
        autojunk=False,
    ).get_opcodes()

    def mapped_boundary(position: int) -> int:
        if position == len(document.text):
            return len(revised_text)
        for tag, source_start, source_end, target_start, target_end in opcodes:
            if source_start <= position <= source_end:
                if tag == "equal":
                    return target_start + position - source_start
                if source_end == source_start:
                    return target_start
                source_width = source_end - source_start
                target_width = target_end - target_start
                return target_start + (
                    (position - source_start) * target_width // source_width
                )
        raise ValueError("Revision boundary could not be mapped.")

    ranges = [
        [mapped_boundary(block.global_start), mapped_boundary(block.global_end)]
        for block in document.blocks
    ]
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
    edited_ranges = [
        (target_start, target_end)
        for tag, _, _, target_start, target_end in opcodes
        if tag != "equal" and target_end > target_start
    ]
    for edited_start, edited_end in edited_ranges:
        for uncovered_start, uncovered_end in _uncovered_ranges(
            edited_start,
            edited_end,
            [ranges[index] for index in owner_indexes],
        ):
            owner_index = min(
                owner_indexes,
                key=lambda index: (
                    _range_distance(
                        ranges[index][0],
                        ranges[index][1],
                        uncovered_start,
                        uncovered_end,
                    ),
                    0 if ranges[index][1] <= uncovered_start else 1,
                    document.blocks[index].global_start,
                    document.blocks[index].global_end,
                    document.blocks[index].block_id,
                ),
            )
            ranges[owner_index][0] = min(
                ranges[owner_index][0],
                uncovered_start,
            )
            ranges[owner_index][1] = max(
                ranges[owner_index][1],
                uncovered_end,
            )

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
        ranges[parent_index][0] = min(ranges[parent_index][0], ranges[index][0])
        ranges[parent_index][1] = max(ranges[parent_index][1], ranges[index][1])

    for edited_start, edited_end in edited_ranges:
        coverage = [
            (max(edited_start, ranges[index][0]), min(edited_end, ranges[index][1]))
            for index in owner_indexes
            if ranges[index][0] < edited_end and edited_start < ranges[index][1]
        ]
        if _covered_length(coverage) != edited_end - edited_start:
            raise VerificationError(
                "revision_text_unmappable",
                "exporting",
                "The persisted revision cannot be mapped to canonical document blocks.",
                False,
            )

    blocks = []
    for block, (start, end) in zip(document.blocks, ranges, strict=True):
        if end < start:
            raise VerificationError(
                "revision_text_unmappable",
                "exporting",
                "The persisted revision cannot be mapped to canonical document blocks.",
                False,
            )
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
        raise VerificationError(
            "revision_text_unmappable",
            "exporting",
            "The persisted revision cannot be mapped to canonical document blocks.",
            False,
        ) from error


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
