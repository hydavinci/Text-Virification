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

    def delete_orphaned_artifacts(
        self,
        referenced_storage_keys: set[str],
        older_than: datetime,
    ) -> list[str]:
        artifact_root = self._root / document_storage.ARTIFACT_NAMESPACE
        if not artifact_root.exists() and not artifact_root.is_symlink():
            return []
        if self._is_reparse_point(artifact_root) or not artifact_root.is_dir():
            self._log_orphaned_artifact_failure(
                document_storage.ARTIFACT_NAMESPACE,
                InvalidUpload("Artifact root is an unsafe directory."),
            )
            return []

        deleted: list[str] = []
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
                job_mtime = datetime.fromtimestamp(
                    job_entry.stat(follow_symlinks=False).st_mtime,
                    UTC,
                )
                self._sweep_artifact_directory(
                    job_id,
                    job_path,
                    referenced_storage_keys,
                    older_than,
                    deleted,
                )
                if job_mtime < older_than:
                    try:
                        job_path.rmdir()
                    except OSError:
                        pass
        return deleted

    def _sweep_artifact_directory(
        self,
        job_id: UUID,
        directory: Path,
        referenced_storage_keys: set[str],
        older_than: datetime,
        deleted: list[str],
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
                        directory_mtime = datetime.fromtimestamp(
                            stat_result.st_mtime,
                            UTC,
                        )
                        self._sweep_artifact_directory(
                            job_id,
                            path,
                            referenced_storage_keys,
                            older_than,
                            deleted,
                        )
                        if directory_mtime < older_than:
                            try:
                                path.rmdir()
                            except OSError:
                                pass
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        raise InvalidUpload(
                            "Artifact orphan candidate is not a regular file."
                        )
                    if storage_key in referenced_storage_keys:
                        continue
                    if datetime.fromtimestamp(stat_result.st_mtime, UTC) >= older_than:
                        continue
                    if self._delete_stale_artifact(job_id, storage_key, older_than):
                        deleted.append(storage_key)
                except Exception as error:
                    self._log_orphaned_artifact_failure(storage_key, error)

    def _delete_stale_artifact(
        self,
        job_id: UUID,
        storage_key: str,
        older_than: datetime,
    ) -> bool:
        return self._artifact_storage.delete_stale_unreferenced(
            job_id,
            storage_key,
            older_than,
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
