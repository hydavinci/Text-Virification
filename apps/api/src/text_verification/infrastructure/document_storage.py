from __future__ import annotations

import logging
import os
import stat
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from uuid import UUID

from text_verification.domain.capabilities import (
    CapabilityProfile,
    default_capability_manifest,
)
from text_verification.domain.documents import FileType

UPLOAD_CHUNK_BYTES = 1024 * 1024
MAX_ZIP_ENTRIES = 10_000
MAX_ZIP_SINGLE_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_ZIP_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
TEXT_FILE_ENCODINGS = ("utf-8", "utf-16", "gbk", "big5")
OriginalNameNormalizer = Callable[[str], str]


@dataclass(frozen=True)
class StoredDocument:
    original_name: str
    path: Path
    file_type: FileType
    size_bytes: int


class InvalidUpload(ValueError):
    pass


class UploadTooLarge(InvalidUpload):
    pass


class UnsupportedFileType(InvalidUpload):
    pass


class UploadCleanupFailed(RuntimeError):
    pass


ARTIFACT_NAMESPACE = "artifacts"


def validate_storage_key(storage_key: str) -> PurePosixPath:
    if (
        not storage_key
        or "\x00" in storage_key
        or "\\" in storage_key
        or storage_key.startswith("/")
        or (len(storage_key) >= 2 and storage_key[1] == ":")
    ):
        raise InvalidUpload("Artifact storage key is unsafe.")
    raw_parts = storage_key.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise InvalidUpload("Artifact storage key is unsafe.")
    return PurePosixPath(*raw_parts)


def build_artifact_storage_key(
    job_id: UUID,
    artifact_id: UUID,
    file_type: FileType | str,
    *,
    subdirectories: tuple[str, ...] = (),
) -> str:
    resolved_file_type = file_type if isinstance(file_type, FileType) else FileType(file_type)
    storage_key = "/".join(
        (
            ARTIFACT_NAMESPACE,
            str(job_id),
            *subdirectories,
            f"{artifact_id}.{resolved_file_type.value}",
        )
    )
    validate_artifact_storage_key(job_id, storage_key)
    return storage_key


def validate_artifact_storage_key(job_id: UUID, storage_key: str) -> PurePosixPath:
    relative_path = validate_storage_key(storage_key)
    expected_prefix = (ARTIFACT_NAMESPACE, str(job_id))
    if len(relative_path.parts) < 3 or relative_path.parts[:2] != expected_prefix:
        raise InvalidUpload(f"Artifact storage key does not belong to job {job_id}.")
    return relative_path


def validate_artifact_identity(
    job_id: UUID,
    artifact_id: UUID,
    file_type: FileType | str,
    storage_key: str,
) -> PurePosixPath:
    resolved_file_type = file_type if isinstance(file_type, FileType) else FileType(file_type)
    relative_path = validate_artifact_storage_key(job_id, storage_key)
    if relative_path.name != f"{artifact_id}.{resolved_file_type.value}":
        raise InvalidUpload(
            "Artifact storage key must match its artifact ID and file type."
        )
    return relative_path


def preserve_original_name(original_name: str) -> str:
    return original_name


def safe_original_name(original_name: str) -> str:
    return _safe_name(original_name)


class DocumentStorage:
    def __init__(
        self,
        root: Path,
        max_upload_bytes: int,
        *,
        profile: CapabilityProfile,
        text_file_encodings: tuple[str, ...] = TEXT_FILE_ENCODINGS,
        original_name_normalizer: OriginalNameNormalizer = safe_original_name,
        cleanup_logger_name: str = __name__,
        cleanup_failure_log_message: str = "document_cleanup_delete_failed",
        cleanup_failure_id_field: str = "document_id",
        allow_existing_directory: bool = False,
        strict_cleanup_failures: bool = True,
    ) -> None:
        self._root = root.expanduser().resolve(strict=False)
        self._max_upload_bytes = max_upload_bytes
        self._profile = profile
        self._allow_existing_directory = allow_existing_directory
        self._strict_cleanup_failures = strict_cleanup_failures
        self._cleanup_logger_name = cleanup_logger_name
        self._cleanup_failure_log_message = cleanup_failure_log_message
        self._cleanup_failure_id_field = cleanup_failure_id_field
        self._text_file_encodings = tuple(text_file_encodings)
        self._original_name_normalizer = original_name_normalizer
        self._supported_file_types = frozenset(
            default_capability_manifest().file_types_for_profile(profile)
        )

    @property
    def supported_file_types(self) -> frozenset[FileType]:
        return self._supported_file_types

    def document_directory(self, document_id: UUID) -> Path:
        return self._root / str(document_id)

    def save_stream(
        self,
        document_id: UUID,
        original_name: str,
        source: BinaryIO,
    ) -> StoredDocument:
        safe_name = _safe_name(original_name)
        stored_original_name = self._original_name_normalizer(original_name)
        file_type = self._file_type_from_name(safe_name)
        document_directory = self.document_directory(document_id)
        self._ensure_safe_storage_path(document_directory)
        document_directory.mkdir(
            parents=True,
            exist_ok=self._allow_existing_directory,
        )
        uploading_path = document_directory / "source.uploading"
        final_path = document_directory / f"source.{file_type.value}"
        self._ensure_safe_storage_path(uploading_path)
        self._ensure_safe_storage_path(final_path)

        size_bytes = 0
        try:
            size_bytes = self._write_stream(uploading_path, source)
            self._validate_content(uploading_path, file_type)
            uploading_path.replace(final_path)
        except Exception:
            try:
                self.delete(document_id)
            except Exception as cleanup_error:
                if self._strict_cleanup_failures:
                    raise UploadCleanupFailed(
                        "Failed to clean up the uploaded job directory."
                    ) from cleanup_error
            raise

        return StoredDocument(
            original_name=stored_original_name,
            path=final_path,
            file_type=file_type,
            size_bytes=size_bytes,
        )

    def save_bytes(self, document_id: UUID, original_name: str, data: bytes) -> StoredDocument:
        return self.save_stream(document_id, original_name, BytesIO(data))

    def source_path(self, document_id: UUID, file_type: FileType | str) -> Path:
        resolved_file_type = file_type if isinstance(file_type, FileType) else FileType(file_type)
        document_directory = self.document_directory(document_id)
        self._ensure_safe_storage_path(document_directory)
        source_path = document_directory / f"source.{resolved_file_type.value}"
        self._ensure_safe_storage_path(source_path)
        if not source_path.is_file():
            raise InvalidUpload("Stored upload is unavailable.")
        return source_path

    def resolve_source(self, document_id: UUID) -> StoredDocument:
        document_directory = self.document_directory(document_id)
        if self._is_reparse_point(document_directory) or not document_directory.is_dir():
            raise InvalidUpload("Original upload was not found.")
        candidates = [
            path
            for path in document_directory.iterdir()
            if path.is_file() and not path.is_symlink() and path.name.startswith("source.")
        ]
        if len(candidates) != 1:
            raise InvalidUpload("Original upload was not found.")
        source_path = candidates[0].resolve(strict=True)
        self._ensure_safe_storage_path(source_path)
        extension = source_path.suffix.lower().removeprefix(".")
        try:
            file_type = FileType(extension)
        except ValueError as error:
            raise InvalidUpload("Stored upload has an unsupported file type.") from error
        if file_type not in self._supported_file_types:
            raise InvalidUpload("Stored upload has an unsupported file type.")
        return StoredDocument(
            original_name=source_path.name,
            path=source_path,
            file_type=file_type,
            size_bytes=source_path.stat().st_size,
        )

    def delete(self, document_id: UUID) -> None:
        self._delete_directory(self.document_directory(document_id))

    def delete_storage_key(self, storage_key: str) -> bool:
        path = self._path_for_storage_key(storage_key)
        if not path.exists():
            return False
        if not path.is_file():
            raise InvalidUpload("Artifact storage key does not reference a regular file.")
        path.unlink()
        self._prune_empty_storage_directories(path.parent)
        return True

    def delete_orphaned_directories(
        self,
        persisted_document_ids: set[UUID],
        older_than: datetime,
    ) -> list[UUID]:
        if not self._root.exists():
            return []

        deleted_document_ids: list[UUID] = []
        for directory in sorted(self._root.iterdir(), key=lambda path: path.name):
            if self._is_reparse_point(directory) or not directory.is_dir():
                continue
            try:
                document_id = UUID(directory.name)
            except ValueError:
                continue
            if str(document_id) != directory.name or document_id in persisted_document_ids:
                continue
            try:
                modified_at = datetime.fromtimestamp(
                    directory.stat(follow_symlinks=False).st_mtime,
                    UTC,
                )
                if modified_at >= older_than:
                    continue
                if not self._is_within_root(directory.resolve(strict=False)):
                    continue
                if self._is_reparse_point(directory):
                    continue
                self._delete_directory(directory)
            except Exception as error:
                logging.getLogger(self._cleanup_logger_name).warning(
                    self._cleanup_failure_log_message,
                    extra={
                        self._cleanup_failure_id_field: str(document_id),
                        "error_type": type(error).__name__,
                    },
                )
                continue
            deleted_document_ids.append(document_id)
        return deleted_document_ids

    def _write_stream(self, uploading_path: Path, source: BinaryIO) -> int:
        size_bytes = 0
        with uploading_path.open("wb") as target:
            while True:
                chunk = source.read(UPLOAD_CHUNK_BYTES)
                if not chunk:
                    return size_bytes
                next_size = size_bytes + len(chunk)
                if next_size > self._max_upload_bytes:
                    raise UploadTooLarge("Upload exceeds the configured maximum size.")
                target.write(chunk)
                size_bytes = next_size

    def _file_type_from_name(self, original_name: str) -> FileType:
        suffix = Path(original_name).suffix.lower()
        if not suffix:
            raise UnsupportedFileType("Upload file name must include a supported extension.")
        try:
            file_type = FileType(suffix.removeprefix("."))
        except ValueError as exc:
            raise UnsupportedFileType(f"Unsupported upload extension: {suffix}") from exc
        if file_type not in self._supported_file_types:
            raise UnsupportedFileType(f"Unsupported upload extension: {suffix}")
        return file_type

    def _validate_content(self, path: Path, file_type: FileType) -> None:
        if file_type == FileType.PDF:
            self._validate_pdf(path)
            return
        if file_type == FileType.DOCX:
            self._validate_docx(path)
            return
        if file_type == FileType.DOC:
            self._validate_doc(path)
            return
        if file_type == FileType.RTF:
            self._validate_rtf(path)
            return
        self._validate_text(path)

    def _validate_pdf(self, path: Path) -> None:
        with path.open("rb") as source:
            if not source.read(5).startswith(b"%PDF-"):
                raise InvalidUpload("Upload content does not match its PDF extension.")

    def _validate_doc(self, path: Path) -> None:
        if path.read_bytes()[:8] != bytes.fromhex("D0CF11E0A1B11AE1"):
            raise InvalidUpload("Upload content does not match its DOC extension.")

    def _validate_rtf(self, path: Path) -> None:
        if not path.read_bytes()[:16].lstrip().startswith(b"{\\rtf"):
            raise InvalidUpload("Upload content does not match its RTF extension.")

    def _validate_text(self, path: Path) -> None:
        if not self._looks_like_text(path):
            raise InvalidUpload("Upload content is not valid text.")

    def _looks_like_text(self, path: Path) -> bool:
        data = path.read_bytes()
        for encoding in self._text_file_encodings:
            try:
                text = data.decode(encoding)
            except UnicodeDecodeError:
                continue
            if self._is_reasonable_text(text):
                return True
        return False

    def _is_reasonable_text(self, text: str) -> bool:
        if not text:
            return True

        printable = 0
        for char in text:
            if char == "\x00":
                return False
            if char.isprintable() or char in "\r\n\t":
                printable += 1
        return printable / len(text) >= 0.85

    def _validate_docx(self, path: Path) -> None:
        try:
            with zipfile.ZipFile(path) as archive:
                infos = archive.infolist()
                if len(infos) > MAX_ZIP_ENTRIES:
                    raise InvalidUpload("DOCX archive has too many entries.")

                total_uncompressed_bytes = 0
                entry_names: set[str] = set()
                for info in infos:
                    self._validate_docx_entry(info)
                    total_uncompressed_bytes += info.file_size
                    if total_uncompressed_bytes > MAX_ZIP_UNCOMPRESSED_BYTES:
                        raise InvalidUpload("DOCX archive exceeds the uncompressed size limit.")
                    entry_names.add(info.filename)

                if "[Content_Types].xml" not in entry_names:
                    raise InvalidUpload("DOCX archive is missing [Content_Types].xml.")
                if "word/document.xml" not in entry_names:
                    raise InvalidUpload("DOCX archive is missing word/document.xml.")
        except zipfile.BadZipFile as exc:
            raise InvalidUpload("DOCX file is not a valid ZIP archive.") from exc

    def _validate_docx_entry(self, info: zipfile.ZipInfo) -> None:
        if info.flag_bits & 0x1:
            raise InvalidUpload(f"DOCX archive entry is encrypted: {info.filename}")
        if info.file_size > MAX_ZIP_SINGLE_UNCOMPRESSED_BYTES:
            raise InvalidUpload(f"DOCX archive entry is too large: {info.filename}")
        if self._is_unsafe_zip_name(info.filename):
            raise InvalidUpload(f"DOCX archive entry has an unsafe path: {info.filename}")

    def _is_unsafe_zip_name(self, name: str) -> bool:
        if not name:
            return True
        if name.startswith(("/", "\\")):
            return True
        if len(name) >= 2 and name[1] == ":":
            return True
        if "\\" in name:
            return True
        return any(part in {".", ".."} for part in PurePosixPath(name).parts)

    def _ensure_safe_storage_path(self, path: Path) -> None:
        if self._is_reparse_point(path):
            raise InvalidUpload(f"Upload path is a reparse point: {path}")
        if not self._is_within_root(path.resolve(strict=False)):
            raise InvalidUpload(f"Upload path escapes storage root: {path}")

    def _path_for_storage_key(self, storage_key: str) -> Path:
        relative_path = validate_storage_key(storage_key)
        path = self._root.joinpath(*relative_path.parts)
        current = self._root
        if self._is_reparse_point(current):
            raise InvalidUpload("Artifact storage key crosses a reparse point.")
        for part in relative_path.parts:
            current /= part
            if self._is_reparse_point(current):
                raise InvalidUpload("Artifact storage key crosses a reparse point.")
        if not self._is_within_root(path.resolve(strict=False)):
            raise InvalidUpload("Artifact storage key escapes the storage root.")
        return path

    def _prune_empty_storage_directories(self, directory: Path) -> None:
        current = directory
        while current != self._root:
            try:
                current.rmdir()
            except OSError:
                return
            current = current.parent

    def _delete_directory(self, document_directory: Path) -> None:
        is_reparse = self._is_reparse_point(document_directory)
        if (
            not document_directory.exists()
            and not document_directory.is_symlink()
            and not is_reparse
        ):
            return

        if document_directory.is_symlink() or is_reparse:
            self._remove_directory_entry(document_directory)
            return

        if not document_directory.is_dir():
            return

        self._delete_tree_contents(document_directory)
        document_directory.rmdir()

    def _delete_tree_contents(self, directory: Path) -> None:
        with os.scandir(directory) as entries:
            for entry in entries:
                child = Path(entry.path)
                if entry.is_dir(follow_symlinks=False) and not self._is_reparse_point(child):
                    self._delete_tree_contents(child)
                    child.rmdir()
                else:
                    self._remove_directory_entry(child)

    def _remove_directory_entry(self, path: Path) -> None:
        if path.is_dir() and not path.is_symlink() and not self._is_reparse_point(path):
            path.rmdir()
            return
        if os.name == "nt" and self._is_reparse_point(path):
            os.rmdir(path)
            return
        path.unlink()

    def _is_within_root(self, path: Path) -> bool:
        try:
            path.relative_to(self._root)
        except ValueError:
            return False
        return True

    def _is_reparse_point(self, path: Path) -> bool:
        if path.is_symlink():
            return True
        if os.name != "nt":
            return False

        isjunction = getattr(os.path, "isjunction", None)
        if callable(isjunction):
            try:
                if isjunction(path):
                    return True
            except OSError:
                pass

        try:
            stat_result = path.lstat()
        except FileNotFoundError:
            return False
        return bool(
            getattr(stat_result, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        )


def _safe_name(original_name: str) -> str:
    name = original_name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name or name in {".", ".."} or "\x00" in name:
        raise InvalidUpload("Upload file name is invalid.")
    return name
