from __future__ import annotations

import io
import zipfile
from uuid import uuid4

import pymupdf
import pytest

from text_verification.domain.capabilities import CapabilityProfile
from text_verification.domain.documents import FileType
from text_verification.infrastructure.document_storage import (
    DocumentStorage,
    InvalidUpload,
)


def make_docx_bytes() -> bytes:
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<w:document/>")
    return data.getvalue()


def make_doc_bytes() -> bytes:
    return bytes.fromhex("D0CF11E0A1B11AE1") + b"\x00" * 16


def make_image_bytes(file_type: FileType, *, width: int = 8, height: int = 6) -> bytes:
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, width, height), False)
    pixmap.clear_with(0x7F3F1F)
    return pixmap.tobytes("png" if file_type is FileType.PNG else "jpeg")


@pytest.fixture
def sync_storage(tmp_path) -> DocumentStorage:
    return DocumentStorage(
        tmp_path,
        max_upload_bytes=25 * 1024 * 1024,
        profile=CapabilityProfile.SYNCHRONOUS_COMPATIBILITY,
    )


def test_document_storage_uses_manifest_sync_profile(sync_storage: DocumentStorage) -> None:
    assert sync_storage.supported_file_types == frozenset(
        {
            FileType.TXT,
            FileType.DOCX,
            FileType.DOC,
            FileType.PDF,
            FileType.RTF,
            FileType.MARKDOWN,
            FileType.CSV,
        }
    )


@pytest.mark.parametrize(
    ("name", "content", "expected"),
    [
        ("sample.txt", b"hello", FileType.TXT),
        ("sample.md", b"# title", FileType.MARKDOWN),
        ("sample.csv", b"a,b\n1,2\n", FileType.CSV),
        ("sample.rtf", br"{\rtf1 hello}", FileType.RTF),
        ("sample.pdf", b"%PDF-1.7\n%%EOF", FileType.PDF),
        ("sample.doc", make_doc_bytes(), FileType.DOC),
        ("sample.docx", make_docx_bytes(), FileType.DOCX),
    ],
)
def test_save_stream_detects_supported_type(
    sync_storage: DocumentStorage,
    name: str,
    content: bytes,
    expected: FileType,
) -> None:
    stored = sync_storage.save_bytes(uuid4(), name, content)

    assert stored.file_type is expected
    assert stored.path.name == f"source.{expected.value}"
    assert stored.path.read_bytes() == content


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("fake.doc", b"plain text"),
        ("fake.rtf", b"plain text"),
        ("fake.md", b"\x00" * 32),
        ("fake.csv", b"\x00" * 32),
    ],
)
def test_save_stream_rejects_invalid_content_for_extension(
    sync_storage: DocumentStorage,
    name: str,
    content: bytes,
) -> None:
    with pytest.raises(InvalidUpload):
        sync_storage.save_bytes(uuid4(), name, content)


def test_document_storage_accepts_big5_text_for_sync_profile(
    sync_storage: DocumentStorage,
) -> None:
    stored = sync_storage.save_bytes(uuid4(), "sample.txt", "體入".encode("big5"))

    assert stored.file_type is FileType.TXT


def test_document_storage_returns_safe_basename_for_path_like_name(
    sync_storage: DocumentStorage,
) -> None:
    stored = sync_storage.save_bytes(uuid4(), "../../繁體文件.txt", "體入".encode("big5"))

    assert stored.original_name == "繁體文件.txt"
    assert stored.path.name == "source.txt"


def test_document_storage_async_profile_accepts_all_canonical_formats(tmp_path) -> None:
    storage = DocumentStorage(
        tmp_path,
        max_upload_bytes=25 * 1024 * 1024,
        profile=CapabilityProfile.ASYNCHRONOUS_JOB,
    )

    assert storage.save_bytes(uuid4(), "sample.doc", make_doc_bytes()).file_type is FileType.DOC


@pytest.mark.parametrize(
    ("name", "file_type"),
    [
        ("sample.png", FileType.PNG),
        ("sample.jpg", FileType.JPG),
        ("sample.jpeg", FileType.JPG),
    ],
)
def test_async_storage_accepts_valid_images_and_normalizes_jpeg_alias(
    tmp_path,
    name: str,
    file_type: FileType,
) -> None:
    storage = DocumentStorage(
        tmp_path,
        max_upload_bytes=25 * 1024 * 1024,
        profile=CapabilityProfile.ASYNCHRONOUS_JOB,
    )

    stored = storage.save_bytes(uuid4(), name, make_image_bytes(file_type))

    assert stored.file_type is file_type
    assert stored.path.name == f"source.{file_type.value}"


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("spoofed.png", b"not an image"),
        ("spoofed.jpg", b"\x89PNG\r\n\x1a\nnot a jpeg"),
        ("corrupt.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 40),
    ],
)
def test_async_storage_rejects_spoofed_or_corrupt_images(
    tmp_path,
    name: str,
    content: bytes,
) -> None:
    storage = DocumentStorage(
        tmp_path,
        max_upload_bytes=25 * 1024 * 1024,
        profile=CapabilityProfile.ASYNCHRONOUS_JOB,
    )

    with pytest.raises(InvalidUpload):
        storage.save_bytes(uuid4(), name, content)
