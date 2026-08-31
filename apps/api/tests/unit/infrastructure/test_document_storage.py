from __future__ import annotations

import io
import zipfile
from uuid import uuid4

import pytest

from text_verification.domain.capabilities import CapabilityProfile
from text_verification.domain.documents import FileType
from text_verification.infrastructure.document_storage import (
    DocumentStorage,
    InvalidUpload,
    UnsupportedFileType,
)


def make_docx_bytes() -> bytes:
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<w:document/>")
    return data.getvalue()


def make_doc_bytes() -> bytes:
    return bytes.fromhex("D0CF11E0A1B11AE1") + b"\x00" * 16


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


def test_document_storage_respects_async_profile_membership(tmp_path) -> None:
    storage = DocumentStorage(
        tmp_path,
        max_upload_bytes=25 * 1024 * 1024,
        profile=CapabilityProfile.ASYNCHRONOUS_JOB,
    )

    with pytest.raises(UnsupportedFileType):
        storage.save_bytes(uuid4(), "sample.doc", make_doc_bytes())
