import io
import zipfile
from pathlib import Path
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
    expected_docx_bytes = make_docx_bytes()

    stored = storage.save_bytes(job_id, "../../客户文档.docx", expected_docx_bytes)

    assert stored.file_type.value == "docx"
    assert stored.path == tmp_path / str(job_id) / "source.docx"
    assert stored.path.read_bytes() == expected_docx_bytes


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


def test_rejects_binary_txt_payload(tmp_path):
    storage = JobStorage(tmp_path, max_upload_bytes=1024)

    with pytest.raises(InvalidUpload):
        storage.save_bytes(uuid4(), "binary.txt", b"\x00" * 128)


def test_rejects_job_directory_symlink_escape(tmp_path):
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    job_id = uuid4()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = storage.job_directory(job_id)

    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    with pytest.raises(InvalidUpload):
        storage.save_bytes(job_id, "sample.txt", b"hello")

    assert not (outside / "source.txt").exists()


def test_rejects_reparse_point_job_directory(monkeypatch, tmp_path):
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    job_id = uuid4()
    job_directory = storage.job_directory(job_id)
    job_directory.mkdir()
    monkeypatch.setattr(
        JobStorage,
        "_is_reparse_point",
        lambda self, path: path == job_directory,
        raising=False,
    )

    with pytest.raises(InvalidUpload):
        storage.save_bytes(job_id, "sample.txt", b"hello")


def test_rejects_docx_without_document_xml(tmp_path):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    with pytest.raises(InvalidUpload, match="word/document.xml"):
        storage.save_bytes(uuid4(), "broken.docx", data.getvalue())


@pytest.mark.parametrize(
    "entry_name",
    [
        "/word/document.xml",
        "C:/word/document.xml",
        "word/../evil.xml",
    ],
)
def test_rejects_docx_unsafe_zip_names(tmp_path, entry_name):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(entry_name, "<x/>")

    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    with pytest.raises(InvalidUpload, match="unsafe path"):
        storage.save_bytes(uuid4(), "large.docx", data.getvalue())


def test_rejects_docx_encrypted_entry(monkeypatch, tmp_path):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<w:document/>")

    original_infolist = zipfile.ZipFile.infolist

    def infolist_with_encrypted_flag(self):
        infos = original_infolist(self)
        for info in infos:
            if info.filename == "word/document.xml":
                info.flag_bits = 1
        return infos

    monkeypatch.setattr(zipfile.ZipFile, "infolist", infolist_with_encrypted_flag)

    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    with pytest.raises(InvalidUpload, match="encrypted"):
        storage.save_bytes(uuid4(), "large.docx", data.getvalue())


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


def test_delete_job_surfaces_failure(tmp_path, monkeypatch):
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    job_id = uuid4()
    storage.save_bytes(job_id, "first.txt", b"first")

    real_unlink = Path.unlink

    def failing_unlink(self, *args, **kwargs):
        raise PermissionError("locked")

    monkeypatch.setattr(Path, "unlink", failing_unlink)

    with pytest.raises(PermissionError, match="locked"):
        storage.delete_job(job_id)

    monkeypatch.setattr(Path, "unlink", real_unlink)


def test_delete_expired_directories_reports_only_removed_ids(tmp_path, monkeypatch):
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    failed = uuid4()
    removed = uuid4()
    storage.save_bytes(failed, "failed.txt", b"first")
    storage.save_bytes(removed, "removed.txt", b"second")

    real_unlink = Path.unlink

    def failing_unlink(self, *args, **kwargs):
        if str(self).endswith("source.txt") and str(failed) in str(self):
            raise PermissionError("locked")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", failing_unlink)

    deleted = storage.delete_expired_directories(set())

    assert set(deleted) == {removed}
    assert failed not in deleted
    assert storage.job_directory(failed).exists()
    assert not storage.job_directory(removed).exists()
