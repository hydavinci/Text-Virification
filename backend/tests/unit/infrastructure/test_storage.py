import io
import zipfile
from uuid import uuid4

import pytest

from text_verification.infrastructure.storage import (
    InvalidUpload,
    JobStorage,
    UploadTooLarge,
)


def make_docx_bytes() -> bytes:
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<w:document/>")
    return data.getvalue()


def test_save_upload_uses_job_directory_and_server_filename(tmp_path):
    storage = JobStorage(tmp_path, max_upload_bytes=25 * 1024 * 1024)
    job_id = uuid4()

    stored = storage.save_bytes(job_id, "../../客户文档.docx", make_docx_bytes())

    assert stored.file_type.value == "docx"
    assert stored.path == tmp_path / str(job_id) / "source.docx"
    assert stored.path.read_bytes() == make_docx_bytes()


def test_rejects_upload_larger_than_configured_limit(tmp_path):
    storage = JobStorage(tmp_path, max_upload_bytes=4)

    with pytest.raises(UploadTooLarge):
        storage.save_bytes(uuid4(), "large.txt", b"12345")


def test_rejects_extension_content_mismatch(tmp_path):
    storage = JobStorage(tmp_path, max_upload_bytes=1024)

    with pytest.raises(InvalidUpload, match="does not match"):
        storage.save_bytes(uuid4(), "fake.pdf", b"plain text")


def test_accepts_pdf_signature(tmp_path):
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    stored = storage.save_bytes(uuid4(), "sample.pdf", b"%PDF-1.7\n%%EOF")
    assert stored.file_type.value == "pdf"


@pytest.mark.parametrize(
    ("name", "payload"),
    [
        ("utf8.txt", "中文".encode()),
        ("utf16.txt", "中文".encode("utf-16")),
        ("gbk.txt", "中文".encode("gbk")),
    ],
)
def test_accepts_supported_text_encodings(tmp_path, name, payload):
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    assert storage.save_bytes(uuid4(), name, payload).file_type.value == "txt"


def test_rejects_docx_without_document_xml(tmp_path):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    with pytest.raises(InvalidUpload, match="word/document.xml"):
        storage.save_bytes(uuid4(), "broken.docx", data.getvalue())


def test_rejects_docx_with_too_many_entries(tmp_path, monkeypatch):
    monkeypatch.setattr("text_verification.infrastructure.storage.MAX_ZIP_ENTRIES", 2)
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<w:document/>")
        archive.writestr("word/extra.xml", "<x/>")
    storage = JobStorage(tmp_path, max_upload_bytes=4096)
    with pytest.raises(InvalidUpload, match="too many entries"):
        storage.save_bytes(uuid4(), "large.docx", data.getvalue())


def test_rejects_docx_declaring_excessive_uncompressed_size(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "text_verification.infrastructure.storage.MAX_ZIP_UNCOMPRESSED_BYTES", 4
    )
    with pytest.raises(InvalidUpload, match="uncompressed size"):
        JobStorage(tmp_path, 4096).save_bytes(
            uuid4(), "large.docx", make_docx_bytes()
        )


def test_delete_job_removes_only_requested_uuid_directory(tmp_path):
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    first = uuid4()
    second = uuid4()
    storage.save_bytes(first, "first.txt", b"first")
    storage.save_bytes(second, "second.txt", b"second")

    storage.delete_job(first)

    assert not storage.job_directory(first).exists()
    assert storage.job_directory(second).exists()
