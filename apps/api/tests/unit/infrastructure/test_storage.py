import io
import logging
import os
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from text_verification.infrastructure.storage import (
    InvalidUpload,
    JobStorage,
    UnsupportedFileType,
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


@pytest.mark.parametrize("name", ["legacy.doc", "legacy.rtf", "notes.md", "rows.csv"])
def test_rejects_non_baseline_extensions_even_if_domain_enum_includes_them(tmp_path, name):
    storage = JobStorage(tmp_path, max_upload_bytes=1024)

    with pytest.raises(UnsupportedFileType):
        storage.save_bytes(uuid4(), name, b"plain text")


def test_source_path_returns_existing_expected_source_file(tmp_path):
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    job_id = uuid4()
    stored = storage.save_bytes(job_id, "sample.txt", b"hello")

    source_path = storage.source_path(job_id, stored.file_type)

    assert source_path == stored.path
    assert source_path.read_bytes() == b"hello"


def test_source_path_rejects_job_directory_outside_storage_root(tmp_path, monkeypatch):
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    job_id = uuid4()
    outside_directory = tmp_path.parent / str(job_id)
    outside_directory.mkdir()
    (outside_directory / "source.txt").write_bytes(b"hello")
    monkeypatch.setattr(storage, "job_directory", lambda actual_job_id: outside_directory)

    with pytest.raises(InvalidUpload, match="escapes storage root"):
        storage.source_path(job_id, "txt")


def test_source_path_rejects_reparse_point_job_directory(monkeypatch, tmp_path):
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    job_id = uuid4()
    stored = storage.save_bytes(job_id, "sample.txt", b"hello")
    job_directory = stored.path.parent
    monkeypatch.setattr(
        JobStorage,
        "_is_reparse_point",
        lambda self, path: path == job_directory,
        raising=False,
    )

    with pytest.raises(InvalidUpload, match="reparse point"):
        storage.source_path(job_id, "txt")


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


def test_delete_orphaned_directories_removes_only_stale_canonical_unpersisted_directories(
    tmp_path,
):
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    cutoff = datetime.now(UTC) - timedelta(hours=1)
    stale_orphan = uuid4()
    fresh_orphan = uuid4()
    stale_persisted = uuid4()
    storage.save_bytes(stale_orphan, "stale.txt", b"stale")
    storage.save_bytes(fresh_orphan, "fresh.txt", b"fresh")
    storage.save_bytes(stale_persisted, "persisted.txt", b"persisted")
    malformed = tmp_path / "not-a-job"
    malformed.mkdir()

    stale_timestamp = (cutoff - timedelta(minutes=1)).timestamp()
    os.utime(storage.job_directory(stale_orphan), (stale_timestamp, stale_timestamp))
    os.utime(storage.job_directory(stale_persisted), (stale_timestamp, stale_timestamp))
    os.utime(malformed, (stale_timestamp, stale_timestamp))

    deleted = storage.delete_orphaned_directories({stale_persisted}, cutoff)

    assert deleted == [stale_orphan]
    assert not storage.job_directory(stale_orphan).exists()
    assert storage.job_directory(fresh_orphan).exists()
    assert storage.job_directory(stale_persisted).exists()
    assert malformed.exists()


def test_delete_orphaned_directories_logs_failure_and_retries_later(
    tmp_path,
    monkeypatch,
    caplog,
):
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    cutoff = datetime.now(UTC) - timedelta(hours=1)
    orphan = uuid4()
    storage.save_bytes(orphan, "orphan.txt", b"orphan")
    stale_timestamp = (cutoff - timedelta(minutes=1)).timestamp()
    os.utime(storage.job_directory(orphan), (stale_timestamp, stale_timestamp))
    real_delete = storage._delete_job_directory
    attempts = 0

    def flaky_delete(path: Path) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("locked")
        real_delete(path)

    monkeypatch.setattr(storage, "_delete_job_directory", flaky_delete)

    with caplog.at_level(logging.WARNING, logger="text_verification.infrastructure.storage"):
        first_deleted = storage.delete_orphaned_directories(set(), cutoff)
        second_deleted = storage.delete_orphaned_directories(set(), cutoff)

    assert first_deleted == []
    assert second_deleted == [orphan]
    assert attempts == 2
    assert not storage.job_directory(orphan).exists()
    assert [record.getMessage() for record in caplog.records] == [
        "cleanup_orphaned_job_delete_failed"
    ]
    assert caplog.records[0].job_id == str(orphan)
    assert caplog.records[0].error_type == "PermissionError"


def test_delete_orphaned_directories_preserves_symlink_entry(tmp_path):
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    cutoff = datetime.now(UTC) - timedelta(hours=1)
    orphan = uuid4()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = storage.job_directory(orphan)
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    deleted = storage.delete_orphaned_directories(set(), cutoff)

    assert deleted == []
    assert link.is_symlink()
    assert outside.exists()
