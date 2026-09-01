from __future__ import annotations

import logging
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from uuid import UUID

from text_verification.domain.capabilities import CapabilityProfile
from text_verification.domain.documents import FileType
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

_PREPARED_ARTIFACT_TOKEN = object()


@dataclass(frozen=True, init=False)
class PreparedArtifact:
    job_id: UUID
    storage_key: str
    path: Path
    file_type: FileType
    size_bytes: int

    def __init__(
        self,
        *,
        job_id: UUID,
        storage_key: str,
        path: Path,
        file_type: FileType,
        size_bytes: int,
        _token: object,
    ) -> None:
        if _token is not _PREPARED_ARTIFACT_TOKEN:
            raise TypeError("PreparedArtifact values must be created by JobStorage.")
        object.__setattr__(self, "job_id", job_id)
        object.__setattr__(self, "storage_key", storage_key)
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "file_type", file_type)
        object.__setattr__(self, "size_bytes", size_bytes)


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

    def write_artifact(
        self,
        job_id: UUID,
        storage_key: str,
        file_type: FileType | str,
        data: bytes,
    ) -> PreparedArtifact:
        resolved_file_type = file_type if isinstance(file_type, FileType) else FileType(file_type)
        relative_path = validate_artifact_storage_key(job_id, storage_key)
        if relative_path.suffix != f".{resolved_file_type.value}":
            raise InvalidUpload("Artifact storage key extension does not match its file type.")

        artifact_path = self._path_for_storage_key(storage_key)
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path = self._path_for_storage_key(storage_key)
        uploading_path = self._path_for_storage_key(f"{storage_key}.uploading")
        try:
            size_bytes = self._write_stream(uploading_path, BytesIO(data))
            artifact_path = self._path_for_storage_key(storage_key)
            uploading_path.replace(artifact_path)
            artifact_path = self._path_for_storage_key(storage_key)
            if not artifact_path.is_file():
                raise InvalidUpload("Artifact storage key does not reference a regular file.")
        except Exception:
            if (
                uploading_path.exists()
                and uploading_path.is_file()
                and not uploading_path.is_symlink()
            ):
                uploading_path.unlink()
            raise

        return PreparedArtifact(
            job_id=job_id,
            storage_key=storage_key,
            path=artifact_path,
            file_type=resolved_file_type,
            size_bytes=size_bytes,
            _token=_PREPARED_ARTIFACT_TOKEN,
        )

    def delete_artifact(self, job_id: UUID, storage_key: str) -> bool:
        validate_artifact_storage_key(job_id, storage_key)
        return self.delete_storage_key(storage_key)

    def _delete_directory(self, document_directory: Path) -> None:
        self._delete_job_directory(document_directory)

    def _delete_job_directory(self, job_directory: Path) -> None:
        super()._delete_directory(job_directory)
