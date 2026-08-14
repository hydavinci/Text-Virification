from __future__ import annotations

import os
import stat
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from uuid import UUID

from text_verification.domain.documents import FileType

UPLOAD_CHUNK_BYTES = 1024 * 1024
MAX_ZIP_ENTRIES = 10_000
MAX_ZIP_SINGLE_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_ZIP_UNCOMPRESSED_BYTES = 200 * 1024 * 1024


@dataclass(frozen=True)
class StoredUpload:
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


class JobStorage:
    def __init__(self, root: Path, max_upload_bytes: int) -> None:
        self._root = root.expanduser().resolve(strict=False)
        self._max_upload_bytes = max_upload_bytes

    def job_directory(self, job_id: UUID) -> Path:
        return self._root / str(job_id)

    def save_stream(self, job_id: UUID, original_name: str, source: BinaryIO) -> StoredUpload:
        file_type = self._file_type_from_name(original_name)
        job_directory = self.job_directory(job_id)
        self._ensure_safe_upload_path(job_directory)
        job_directory.mkdir(parents=True, exist_ok=True)
        uploading_path = job_directory / "source.uploading"
        final_path = job_directory / f"source.{file_type.value}"
        self._ensure_safe_upload_path(uploading_path)
        self._ensure_safe_upload_path(final_path)

        size_bytes = 0
        try:
            size_bytes = self._write_stream(uploading_path, source)
            actual_file_type = self._detect_content_type(uploading_path)
            if actual_file_type != file_type:
                raise InvalidUpload("Upload extension does not match content.")
            uploading_path.replace(final_path)
        except Exception:
            try:
                self.delete_job(job_id)
            except Exception as cleanup_error:
                raise UploadCleanupFailed(
                    "Failed to clean up the uploaded job directory."
                ) from cleanup_error
            raise

        return StoredUpload(
            original_name=original_name,
            path=final_path,
            file_type=file_type,
            size_bytes=size_bytes,
        )

    def save_bytes(self, job_id: UUID, original_name: str, data: bytes) -> StoredUpload:
        return self.save_stream(job_id, original_name, BytesIO(data))

    def delete_job(self, job_id: UUID) -> None:
        self._delete_job_directory(self.job_directory(job_id))

    def delete_expired_directories(self, live_job_ids: set[UUID]) -> list[UUID]:
        if not self._root.exists():
            return []

        deleted_job_ids: list[UUID] = []
        for directory in sorted(self._root.iterdir(), key=lambda path: path.name):
            if not directory.is_dir() and not self._is_reparse_point(directory):
                continue
            try:
                job_id = UUID(directory.name)
            except ValueError:
                continue
            if str(job_id) != directory.name or job_id in live_job_ids:
                continue
            try:
                self._delete_job_directory(directory)
            except Exception:
                continue
            deleted_job_ids.append(job_id)
        return deleted_job_ids

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
            return FileType(suffix.removeprefix("."))
        except ValueError as exc:
            raise UnsupportedFileType(f"Unsupported upload extension: {suffix}") from exc

    def _detect_content_type(self, path: Path) -> FileType:
        if self._looks_like_pdf(path):
            return FileType.PDF
        if zipfile.is_zipfile(path):
            self._validate_docx(path)
            return FileType.DOCX
        if self._looks_like_text(path):
            return FileType.TXT
        raise InvalidUpload("Upload content is not a supported DOCX, PDF, or TXT file.")

    def _looks_like_pdf(self, path: Path) -> bool:
        with path.open("rb") as source:
            return source.read(5).startswith(b"%PDF-")

    def _looks_like_text(self, path: Path) -> bool:
        data = path.read_bytes()
        for encoding in ("utf-8", "utf-16", "gbk"):
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
        parts = PurePosixPath(name).parts
        return any(part in {".", ".."} for part in parts)

    def _ensure_safe_upload_path(self, path: Path) -> None:
        if self._is_reparse_point(path):
            raise InvalidUpload(f"Upload path is a reparse point: {path}")
        if not self._is_within_root(path.resolve(strict=False)):
            raise InvalidUpload(f"Upload path escapes storage root: {path}")

    def _delete_job_directory(self, job_directory: Path) -> None:
        is_reparse = self._is_reparse_point(job_directory)
        if not job_directory.exists() and not job_directory.is_symlink() and not is_reparse:
            return

        if job_directory.is_symlink() or is_reparse:
            self._remove_directory_entry(job_directory)
            return

        if not job_directory.is_dir():
            return

        self._delete_tree_contents(job_directory)
        job_directory.rmdir()

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
