from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from text_verification.domain.capabilities import CapabilityProfile
from text_verification.domain.documents import FileType
from text_verification.infrastructure import document_storage
from text_verification.infrastructure.artifact_storage import (
    ArtifactOrphanCandidate,
    ArtifactStorage,
    ArtifactVerificationHandle,
)

logger = logging.getLogger(__name__)

JOB_TEXT_FILE_ENCODINGS = ("utf-8", "utf-16", "gbk")

DocumentStorage = document_storage.DocumentStorage
InvalidUpload = document_storage.InvalidUpload
StoredUpload = document_storage.StoredDocument
UnsupportedFileType = document_storage.UnsupportedFileType
UploadCleanupFailed = document_storage.UploadCleanupFailed
UploadTooLarge = document_storage.UploadTooLarge
build_artifact_storage_key = document_storage.build_artifact_storage_key
validate_artifact_storage_key = document_storage.validate_artifact_storage_key
validate_artifact_identity = document_storage.validate_artifact_identity

class JobStorage(DocumentStorage):
    def __init__(self, root: Path, max_upload_bytes: int) -> None:
        super().__init__(
            root,
            max_upload_bytes,
            profile=CapabilityProfile.ASYNCHRONOUS_JOB,
            text_file_encodings=JOB_TEXT_FILE_ENCODINGS,
            original_name_normalizer=document_storage.preserve_original_name,
            cleanup_logger_name=logger.name,
            cleanup_failure_log_message="cleanup_orphaned_job_delete_failed",
            cleanup_failure_id_field="job_id",
            allow_existing_directory=True,
            strict_cleanup_failures=True,
        )
        self._artifact_storage = ArtifactStorage(self._root, max_upload_bytes)

    def document_directory(self, document_id: UUID) -> Path:
        return self.job_directory(document_id)

    def job_directory(self, job_id: UUID) -> Path:
        return self._root / str(job_id)

    def delete(self, document_id: UUID) -> None:
        self.delete_job(document_id)

    def delete_job(self, job_id: UUID) -> None:
        self._delete_job_directory(self.job_directory(job_id))

    def publish_verified_artifact(
        self,
        job_id: UUID,
        artifact_id: UUID,
        storage_key: str,
        file_type: FileType | str,
        data: bytes,
    ) -> ArtifactVerificationHandle:
        return self._artifact_storage.publish_verified(
            job_id,
            artifact_id,
            storage_key,
            file_type,
            data,
        )

    def open_verified_artifact(
        self,
        job_id: UUID,
        artifact_id: UUID,
        storage_key: str,
        file_type: FileType | str,
        *,
        expected_size: int,
        expected_digest: str,
    ) -> ArtifactVerificationHandle:
        return self._artifact_storage.open_verified(
            job_id,
            artifact_id,
            storage_key,
            file_type,
            expected_size=expected_size,
            expected_digest=expected_digest,
        )

    def delete_artifact(self, job_id: UUID, storage_key: str) -> bool:
        return self._artifact_storage.delete_owned(job_id, storage_key)

    def is_artifact_missing(
        self,
        job_id: UUID,
        artifact_id: UUID,
        storage_key: str,
        file_type: FileType | str,
    ) -> bool:
        return self._artifact_storage.is_artifact_missing(
            job_id,
            artifact_id,
            storage_key,
            file_type,
        )

    def discover_stale_orphaned_artifacts(
        self,
        older_than: datetime,
    ) -> tuple[ArtifactOrphanCandidate, ...]:
        artifact_root = self._root / document_storage.ARTIFACT_NAMESPACE
        if not artifact_root.exists() and not artifact_root.is_symlink():
            return ()
        if self._is_reparse_point(artifact_root) or not artifact_root.is_dir():
            self._log_orphaned_artifact_failure(
                document_storage.ARTIFACT_NAMESPACE,
                InvalidUpload("Artifact root is an unsafe directory."),
            )
            return ()

        candidates: list[ArtifactOrphanCandidate] = []
        with os.scandir(artifact_root) as job_entries:
            for job_entry in job_entries:
                job_path = Path(job_entry.path)
                if job_entry.is_symlink() or self._is_reparse_point(job_path):
                    self._log_orphaned_artifact_failure(
                        job_path.relative_to(self._root).as_posix(),
                        InvalidUpload("Artifact job directory is a reparse point."),
                    )
                    continue
                if not job_entry.is_dir(follow_symlinks=False):
                    continue
                try:
                    job_id = UUID(job_entry.name)
                except ValueError:
                    continue
                if str(job_id) != job_entry.name:
                    continue
                self._discover_stale_artifact_candidates(
                    job_id,
                    job_path,
                    older_than,
                    candidates,
                )
        return tuple(candidates)

    def delete_stale_orphaned_artifact(
        self,
        candidate: ArtifactOrphanCandidate,
        older_than: datetime,
        *,
        prune_empty_directories: bool,
    ) -> bool:
        return self._artifact_storage.delete_stale_candidate(
            candidate,
            older_than,
            prune_empty_directories=prune_empty_directories,
        )

    def _discover_stale_artifact_candidates(
        self,
        job_id: UUID,
        directory: Path,
        older_than: datetime,
        candidates: list[ArtifactOrphanCandidate],
    ) -> None:
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                storage_key = path.relative_to(self._root).as_posix()
                try:
                    stat_result = entry.stat(follow_symlinks=False)
                    if entry.is_symlink() or self._is_reparse_point(path):
                        raise InvalidUpload(
                            "Artifact orphan candidate is a reparse point."
                        )
                    if entry.is_dir(follow_symlinks=False):
                        self._discover_stale_artifact_candidates(
                            job_id,
                            path,
                            older_than,
                            candidates,
                        )
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        raise InvalidUpload(
                            "Artifact orphan candidate is not a regular file."
                        )
                    if datetime.fromtimestamp(stat_result.st_mtime, UTC) >= older_than:
                        continue
                    candidates.append(
                        self._parse_orphan_candidate(job_id, storage_key)
                    )
                except Exception as error:
                    self._log_orphaned_artifact_failure(storage_key, error)

    def _parse_orphan_candidate(
        self,
        job_id: UUID,
        storage_key: str,
    ) -> ArtifactOrphanCandidate:
        try:
            relative_path = validate_artifact_storage_key(job_id, storage_key)
            artifact_text, separator, file_type_text = relative_path.name.rpartition(".")
            if not separator:
                raise ValueError("Artifact filename has no file type suffix.")
            artifact_id = UUID(artifact_text)
            if str(artifact_id) != artifact_text:
                raise ValueError("Artifact filename does not use a canonical UUID.")
            file_type = FileType(file_type_text)
            validate_artifact_identity(
                job_id,
                artifact_id,
                file_type,
                storage_key,
            )
            return ArtifactOrphanCandidate(
                job_id,
                artifact_id,
                file_type,
                storage_key,
                storage_key,
            )
        except (InvalidUpload, ValueError):
            return self._parse_uploading_orphan_candidate(
                job_id,
                storage_key,
            )

    def _parse_uploading_orphan_candidate(
        self,
        job_id: UUID,
        storage_key: str,
    ) -> ArtifactOrphanCandidate:
        try:
            relative_path = validate_artifact_storage_key(job_id, storage_key)
            temporary_name = relative_path.name
            temporary_suffix = ".uploading"
            if (
                not temporary_name.startswith(".")
                or not temporary_name.endswith(temporary_suffix)
            ):
                raise ValueError("Artifact filename is not a temporary upload.")
            artifact_name, separator, temporary_id = temporary_name[
                1 : -len(temporary_suffix)
            ].rpartition(".")
            if not separator or UUID(temporary_id).hex != temporary_id:
                raise ValueError("Artifact temporary upload ID is not canonical.")
            artifact_text, separator, file_type_text = artifact_name.rpartition(".")
            if not separator:
                raise ValueError("Artifact filename has no file type suffix.")
            artifact_id = UUID(artifact_text)
            if str(artifact_id) != artifact_text:
                raise ValueError("Artifact filename does not use a canonical UUID.")
            file_type = FileType(file_type_text)
            canonical_storage_key = "/".join(
                (*relative_path.parts[:-1], artifact_name)
            )
            validate_artifact_identity(
                job_id,
                artifact_id,
                file_type,
                canonical_storage_key,
            )
        except (InvalidUpload, ValueError) as error:
            raise InvalidUpload(
                "Artifact orphan candidate does not have canonical identity."
            ) from error
        return ArtifactOrphanCandidate(
            job_id,
            artifact_id,
            file_type,
            canonical_storage_key,
            storage_key,
        )

    def _log_orphaned_artifact_failure(
        self,
        storage_key: str,
        error: Exception,
    ) -> None:
        logger.warning(
            "cleanup_orphaned_artifact_delete_failed",
            extra={
                "storage_key": storage_key,
                "error_type": type(error).__name__,
            },
        )

    def _delete_directory(self, document_directory: Path) -> None:
        self._delete_job_directory(document_directory)

    def _delete_job_directory(self, job_directory: Path) -> None:
        super()._delete_directory(job_directory)
