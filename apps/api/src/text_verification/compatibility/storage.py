from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import BinaryIO
from uuid import UUID

from text_verification.domain.capabilities import (
    CapabilityProfile,
    default_capability_manifest,
)
from text_verification.infrastructure.document_storage import (
    DocumentStorage,
    InvalidUpload,
    StoredDocument,
    UnsupportedFileType,
    UploadCleanupFailed,
    UploadTooLarge,
    safe_original_name,
)

logger = logging.getLogger(__name__)
COMPATIBILITY_TEXT_FILE_ENCODINGS = ("utf-8", "utf-16", "gbk", "big5")


class CompatibilityUploadError(ValueError):
    pass


class CompatibilityUploadTooLarge(CompatibilityUploadError):
    pass


@dataclass(frozen=True)
class StoredCompatibilityUpload:
    file_id: UUID
    original_name: str
    path: Path
    extension: str
    size_bytes: int


class CompatibilityStorage:
    """Isolated storage for synchronous legacy-compatible analysis and export."""

    def __init__(self, root: Path, max_upload_bytes: int) -> None:
        self._storage = DocumentStorage(
            root.expanduser().resolve(strict=False) / "compatibility",
            max_upload_bytes,
            profile=CapabilityProfile.SYNCHRONOUS_COMPATIBILITY,
            text_file_encodings=COMPATIBILITY_TEXT_FILE_ENCODINGS,
            original_name_normalizer=safe_original_name,
            cleanup_logger_name=logger.name,
            cleanup_failure_log_message="compatibility_cleanup_delete_failed",
            cleanup_failure_id_field="file_id",
            allow_existing_directory=False,
            strict_cleanup_failures=False,
        )
        self._root = self._storage._root
        self._max_upload_bytes = self._storage._max_upload_bytes
        self._supported_extensions = default_capability_manifest().extensions_for_profile(
            CapabilityProfile.SYNCHRONOUS_COMPATIBILITY
        )

    @property
    def supported_extensions(self) -> frozenset[str]:
        return self._supported_extensions

    def save_stream(
        self,
        file_id: UUID,
        original_name: str,
        source: BinaryIO,
    ) -> StoredCompatibilityUpload:
        try:
            stored = self._storage.save_stream(file_id, original_name, source)
        except UploadTooLarge as error:
            raise CompatibilityUploadTooLarge(str(error)) from error
        except (InvalidUpload, UnsupportedFileType, UploadCleanupFailed) as error:
            raise CompatibilityUploadError(str(error)) from error
        return self._to_compatibility_upload(file_id, stored)

    def resolve_source(self, file_id: UUID) -> tuple[Path, str]:
        try:
            stored = self._storage.resolve_source(file_id)
        except InvalidUpload as error:
            raise CompatibilityUploadError(str(error)) from error
        return stored.path, stored.file_type.value

    def delete(self, file_id: UUID) -> None:
        self._storage.delete(file_id)

    def delete_stale_directories(self, older_than: datetime) -> list[UUID]:
        """Delete stale canonical UUID directories without following links."""
        if self._is_reparse_point(self._root) or not self._root.is_dir():
            return []
        if self._root.resolve(strict=False) != self._root:
            return []
        return self._storage.delete_orphaned_directories(set(), older_than)

    def _to_compatibility_upload(
        self,
        file_id: UUID,
        stored: StoredDocument,
    ) -> StoredCompatibilityUpload:
        return StoredCompatibilityUpload(
            file_id=file_id,
            original_name=stored.original_name,
            path=stored.path,
            extension=stored.file_type.value,
            size_bytes=stored.size_bytes,
        )

    def _is_reparse_point(self, path: Path) -> bool:
        return self._storage._is_reparse_point(path)
