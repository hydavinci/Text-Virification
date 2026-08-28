from __future__ import annotations

import logging
import os
import shutil
import stat
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from uuid import UUID

UPLOAD_CHUNK_BYTES = 1024 * 1024
SUPPORTED_EXTENSIONS = {"csv", "doc", "docx", "md", "pdf", "rtf", "txt"}

logger = logging.getLogger(__name__)


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
        self._root = root.expanduser().resolve(strict=False) / "compatibility"
        self._max_upload_bytes = max_upload_bytes

    def save_stream(
        self,
        file_id: UUID,
        original_name: str,
        source: BinaryIO,
    ) -> StoredCompatibilityUpload:
        safe_name = self._safe_name(original_name)
        extension = Path(safe_name).suffix.lower().removeprefix(".")
        if extension not in SUPPORTED_EXTENSIONS:
            raise CompatibilityUploadError(f"Unsupported upload extension: .{extension}")

        directory = self._directory(file_id)
        directory.mkdir(parents=True, exist_ok=False)
        uploading_path = directory / "source.uploading"
        source_path = directory / f"source.{extension}"
        size_bytes = 0
        try:
            with uploading_path.open("xb") as target:
                while chunk := source.read(UPLOAD_CHUNK_BYTES):
                    size_bytes += len(chunk)
                    if size_bytes > self._max_upload_bytes:
                        raise CompatibilityUploadTooLarge(
                            "Upload exceeds the configured maximum size."
                        )
                    target.write(chunk)
            self._validate_content(uploading_path, extension)
            uploading_path.replace(source_path)
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise

        return StoredCompatibilityUpload(
            file_id=file_id,
            original_name=safe_name,
            path=source_path,
            extension=extension,
            size_bytes=size_bytes,
        )

    def resolve_source(self, file_id: UUID) -> tuple[Path, str]:
        directory = self._directory(file_id)
        if directory.is_symlink() or not directory.is_dir():
            raise CompatibilityUploadError("Original upload was not found.")
        candidates = [
            path
            for path in directory.iterdir()
            if path.is_file() and not path.is_symlink() and path.name.startswith("source.")
        ]
        if len(candidates) != 1:
            raise CompatibilityUploadError("Original upload was not found.")
        source_path = candidates[0].resolve(strict=True)
        self._ensure_within_root(source_path)
        extension = source_path.suffix.lower().removeprefix(".")
        if extension not in SUPPORTED_EXTENSIONS:
            raise CompatibilityUploadError("Stored upload has an unsupported file type.")
        return source_path, extension

    def delete(self, file_id: UUID) -> None:
        directory = self._directory(file_id)
        self._delete_directory(directory)

    def delete_stale_directories(self, older_than: datetime) -> list[UUID]:
        """Delete stale canonical UUID directories without following links."""
        if self._is_reparse_point(self._root) or not self._root.is_dir():
            return []
        if self._root.resolve(strict=False) != self._root:
            return []

        deleted_ids: list[UUID] = []
        try:
            directories = sorted(self._root.iterdir(), key=lambda path: path.name)
        except OSError:
            return []

        for directory in directories:
            if self._is_reparse_point(directory) or not directory.is_dir():
                continue
            try:
                file_id = UUID(directory.name)
            except ValueError:
                continue
            if str(file_id) != directory.name:
                continue
            try:
                resolved = directory.resolve(strict=False)
                self._ensure_within_root(resolved)
                if resolved != directory:
                    continue
                modified_at = datetime.fromtimestamp(
                    directory.stat(follow_symlinks=False).st_mtime,
                    UTC,
                )
                if modified_at >= older_than:
                    continue
                self._delete_directory(directory)
            except Exception as error:
                logger.warning(
                    "compatibility_cleanup_delete_failed",
                    extra={
                        "file_id": str(file_id),
                        "error_type": type(error).__name__,
                    },
                )
                continue
            deleted_ids.append(file_id)
        return deleted_ids

    def _directory(self, file_id: UUID) -> Path:
        directory = self._root / str(file_id)
        self._ensure_within_root(directory.resolve(strict=False))
        return directory

    def _delete_directory(self, directory: Path) -> None:
        is_reparse_point = self._is_reparse_point(directory)
        if not directory.exists() and not directory.is_symlink() and not is_reparse_point:
            return
        if directory.is_symlink() or is_reparse_point:
            self._remove_entry(directory)
            return
        if not directory.is_dir():
            return
        self._delete_tree_contents(directory)
        directory.rmdir()

    def _delete_tree_contents(self, directory: Path) -> None:
        with os.scandir(directory) as entries:
            for entry in entries:
                child = Path(entry.path)
                if entry.is_dir(follow_symlinks=False) and not self._is_reparse_point(child):
                    self._delete_tree_contents(child)
                    child.rmdir()
                else:
                    self._remove_entry(child)

    def _remove_entry(self, path: Path) -> None:
        if path.is_dir() and not path.is_symlink() and not self._is_reparse_point(path):
            path.rmdir()
            return
        if os.name == "nt" and self._is_reparse_point(path):
            os.rmdir(path)
            return
        path.unlink()

    def _ensure_within_root(self, path: Path) -> None:
        try:
            path.relative_to(self._root)
        except ValueError as error:
            raise CompatibilityUploadError("Upload path escapes the storage root.") from error

    def _safe_name(self, original_name: str) -> str:
        name = original_name.replace("\\", "/").rsplit("/", 1)[-1].strip()
        if not name or name in {".", ".."} or "\x00" in name:
            raise CompatibilityUploadError("Upload file name is invalid.")
        return name

    def _validate_content(self, path: Path, extension: str) -> None:
        if extension == "pdf":
            if not path.read_bytes()[:5].startswith(b"%PDF-"):
                raise CompatibilityUploadError("Upload content does not match its PDF extension.")
            return
        if extension == "docx":
            self._validate_docx(path)
            return
        if extension == "doc":
            if path.read_bytes()[:8] != bytes.fromhex("D0CF11E0A1B11AE1"):
                raise CompatibilityUploadError("Upload content does not match its DOC extension.")
            return
        if extension == "rtf":
            if not path.read_bytes()[:16].lstrip().startswith(b"{\\rtf"):
                raise CompatibilityUploadError("Upload content does not match its RTF extension.")
            return
        if not self._is_text(path):
            raise CompatibilityUploadError("Upload content is not valid text.")

    def _validate_docx(self, path: Path) -> None:
        try:
            with zipfile.ZipFile(path) as archive:
                names = set()
                total_size = 0
                for info in archive.infolist():
                    if self._unsafe_zip_name(info.filename) or info.flag_bits & 0x1:
                        raise CompatibilityUploadError("DOCX archive contains an unsafe entry.")
                    if info.file_size > 100 * 1024 * 1024:
                        raise CompatibilityUploadError("DOCX archive entry is too large.")
                    total_size += info.file_size
                    if total_size > 200 * 1024 * 1024:
                        raise CompatibilityUploadError("DOCX archive is too large.")
                    names.add(info.filename)
                if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                    raise CompatibilityUploadError("DOCX archive is missing required entries.")
        except zipfile.BadZipFile as error:
            raise CompatibilityUploadError("Upload content is not a valid DOCX archive.") from error

    def _unsafe_zip_name(self, name: str) -> bool:
        if not name or name.startswith(("/", "\\")) or "\\" in name:
            return True
        if len(name) >= 2 and name[1] == ":":
            return True
        return any(part in {".", ".."} for part in PurePosixPath(name).parts)

    def _is_text(self, path: Path) -> bool:
        data = path.read_bytes()
        for encoding in ("utf-8", "utf-16", "gbk", "big5"):
            try:
                text = data.decode(encoding)
            except UnicodeDecodeError:
                continue
            if not text:
                return True
            printable = sum(char.isprintable() or char in "\r\n\t" for char in text)
            if "\x00" not in text and printable / len(text) >= 0.85:
                return True
        return False

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
