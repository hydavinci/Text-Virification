from __future__ import annotations

import logging
from pathlib import Path
from uuid import UUID

from text_verification.domain.capabilities import CapabilityProfile
from text_verification.infrastructure import document_storage

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

    def document_directory(self, document_id: UUID) -> Path:
        return self.job_directory(document_id)

    def job_directory(self, job_id: UUID) -> Path:
        return self._root / str(job_id)

    def delete(self, document_id: UUID) -> None:
        self.delete_job(document_id)

    def delete_job(self, job_id: UUID) -> None:
        self._delete_job_directory(self.job_directory(job_id))

    def delete_artifact(self, job_id: UUID, storage_key: str) -> bool:
        validate_artifact_storage_key(job_id, storage_key)
        return self.delete_storage_key(storage_key)

    def _delete_directory(self, document_directory: Path) -> None:
        self._delete_job_directory(document_directory)

    def _delete_job_directory(self, job_directory: Path) -> None:
        super()._delete_directory(job_directory)
