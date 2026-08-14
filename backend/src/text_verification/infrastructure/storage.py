from __future__ import annotations

import shutil
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


class JobStorage:
    def __init__(self, root: Path, max_upload_bytes: int) -> None:
        self._root = root.expanduser().resolve(strict=False)
        self._max_upload_bytes = max_upload_bytes

    def job_directory(self, job_id: UUID) -> Path:
        return self._root / str(job_id)

    def save_stream(self, job_id: UUID, original_name: str, source: BinaryIO) -> StoredUpload:
        file_type = self._file_type_from_name(original_name)
        job_directory = self.job_directory(job_id)
        uploading_path = job_directory / "source.uploading"
        final_path = job_directory / f"source.{file_type.value}"
        job_directory.mkdir(parents=True, exist_ok=True)

        size_bytes = 0
        try:
            size_bytes = self._write_stream(uploading_path, source)
            actual_file_type = self._detect_content_type(uploading_path)
            if actual_file_type != file_type:
                raise InvalidUpload("Upload extension does not match content.")
            uploading_path.replace(final_path)
        except Exception:
            self._remove_job_directory(job_directory)
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
        self._remove_job_directory(self.job_directory(job_id))

    def delete_expired_directories(self, live_job_ids: set[UUID]) -> list[UUID]:
        if not self._root.exists():
            return []

        deleted_job_ids: list[UUID] = []
        for directory in sorted(self._root.iterdir(), key=lambda path: path.name):
            if not directory.is_dir():
                continue
            try:
                job_id = UUID(directory.name)
            except ValueError:
                continue
            if str(job_id) != directory.name or job_id in live_job_ids:
                continue
            self._remove_job_directory(directory)
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
            raise InvalidUpload("Upload file name must include a supported extension.")
        try:
            return FileType(suffix.removeprefix("."))
        except ValueError as exc:
            raise InvalidUpload(f"Unsupported upload extension: {suffix}") from exc

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
                data.decode(encoding)
            except UnicodeDecodeError:
                continue
            return True
        return False

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

    def _remove_job_directory(self, job_directory: Path) -> None:
        shutil.rmtree(job_directory, ignore_errors=True)
