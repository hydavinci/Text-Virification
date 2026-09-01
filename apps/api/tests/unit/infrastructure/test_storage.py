import io
import logging
import os
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest

from text_verification.domain.documents import FileType
from text_verification.infrastructure import storage as storage_module
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


def test_job_storage_uses_manifest_async_profile(tmp_path):
    storage = JobStorage(tmp_path, max_upload_bytes=1024)

    assert storage.supported_file_types == frozenset(
        {FileType.DOCX, FileType.PDF, FileType.TXT}
    )


def test_save_upload_uses_job_directory_and_server_filename(tmp_path):
    storage = JobStorage(tmp_path, max_upload_bytes=25 * 1024 * 1024)
    job_id = uuid4()
    expected_docx_bytes = make_docx_bytes()
    original_name = "../../客户文档.docx"

    stored = storage.save_bytes(job_id, original_name, expected_docx_bytes)

    assert stored.file_type.value == "docx"
    assert stored.original_name == original_name
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


def test_rejects_big5_text_to_preserve_async_job_contract(tmp_path):
    storage = JobStorage(tmp_path, max_upload_bytes=1024)

    with pytest.raises(InvalidUpload, match="valid text"):
        storage.save_bytes(uuid4(), "legacy-big5.txt", "體入".encode("big5"))


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
    monkeypatch.setattr("text_verification.infrastructure.document_storage.MAX_ZIP_ENTRIES", 2)
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
        "text_verification.infrastructure.document_storage.MAX_ZIP_UNCOMPRESSED_BYTES", 4
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


def test_delete_storage_key_removes_root_relative_export(tmp_path) -> None:
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    export_path = tmp_path / "exports" / "reviewed.txt"
    export_path.parent.mkdir()
    export_path.write_text("reviewed", encoding="utf-8")

    assert storage.delete_storage_key("exports/reviewed.txt") is True
    assert not export_path.exists()
    assert storage.delete_storage_key("exports/reviewed.txt") is False


def test_artifact_storage_key_builder_uses_job_owned_namespace() -> None:
    job_id = uuid4()
    artifact_id = uuid4()

    storage_key = storage_module.build_artifact_storage_key(
        job_id,
        artifact_id,
        FileType.DOCX,
    )

    assert storage_key == f"artifacts/{job_id}/{artifact_id}.docx"


def test_publish_artifact_retry_reuses_identical_existing_file(tmp_path) -> None:
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    job_id = uuid4()
    artifact_id = uuid4()
    storage_key = storage_module.build_artifact_storage_key(
        job_id,
        artifact_id,
        FileType.TXT,
    )

    first = storage.publish_artifact(
        job_id,
        artifact_id,
        storage_key,
        FileType.TXT,
        b"same content",
    )
    second = storage.publish_artifact(
        job_id,
        artifact_id,
        storage_key,
        FileType.TXT,
        b"same content",
    )

    assert first.created is True
    assert second.created is False
    assert second.size_bytes == first.size_bytes
    assert second.content_sha256 == first.content_sha256
    assert first.path.read_bytes() == b"same content"


def test_publish_artifact_rejects_different_content_without_overwrite(tmp_path) -> None:
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    job_id = uuid4()
    artifact_id = uuid4()
    storage_key = storage_module.build_artifact_storage_key(
        job_id,
        artifact_id,
        FileType.TXT,
    )
    published = storage.publish_artifact(
        job_id,
        artifact_id,
        storage_key,
        FileType.TXT,
        b"original",
    )

    with pytest.raises(InvalidUpload, match="different content"):
        storage.publish_artifact(
            job_id,
            artifact_id,
            storage_key,
            FileType.TXT,
            b"replacement",
        )

    assert published.path.read_bytes() == b"original"


def test_fallback_publish_is_non_clobbering(
    tmp_path,
    monkeypatch,
) -> None:
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    monkeypatch.setattr(
        storage,
        "_supports_descriptor_artifact_operations",
        lambda: False,
    )
    job_id = uuid4()
    artifact_id = uuid4()
    storage_key = storage_module.build_artifact_storage_key(
        job_id,
        artifact_id,
        FileType.TXT,
    )
    published = storage.publish_artifact(
        job_id,
        artifact_id,
        storage_key,
        FileType.TXT,
        b"fallback",
    )

    with pytest.raises(InvalidUpload, match="different content"):
        storage.publish_artifact(
            job_id,
            artifact_id,
            storage_key,
            FileType.TXT,
            b"changed!",
        )

    assert published.path.read_bytes() == b"fallback"


def test_concurrent_identical_artifact_writers_publish_once(tmp_path) -> None:
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    job_id = uuid4()
    artifact_id = uuid4()
    storage_key = storage_module.build_artifact_storage_key(
        job_id,
        artifact_id,
        FileType.TXT,
    )
    start = Barrier(2)

    def publish():
        start.wait(timeout=2)
        return storage.publish_artifact(
            job_id,
            artifact_id,
            storage_key,
            FileType.TXT,
            b"concurrent",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: publish(), range(2)))

    assert sorted(result.created for result in results) == [False, True]
    assert {result.content_sha256 for result in results} == {
        results[0].content_sha256
    }
    assert results[0].path.read_bytes() == b"concurrent"


def test_verify_artifact_rejects_same_size_content_change(tmp_path) -> None:
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    job_id = uuid4()
    artifact_id = uuid4()
    storage_key = storage_module.build_artifact_storage_key(
        job_id,
        artifact_id,
        FileType.TXT,
    )
    published = storage.publish_artifact(
        job_id,
        artifact_id,
        storage_key,
        FileType.TXT,
        b"first",
    )
    published.path.write_bytes(b"other")

    with pytest.raises(InvalidUpload, match="fingerprint"):
        storage.verify_artifact(published)


def test_verify_artifact_returns_owned_reference_for_nested_path(tmp_path) -> None:
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    job_id = uuid4()
    artifact_id = uuid4()
    storage_key = storage_module.build_artifact_storage_key(
        job_id,
        artifact_id,
        FileType.TXT,
        subdirectories=("reports", "reviewed"),
    )

    published = storage.publish_artifact(
        job_id,
        artifact_id,
        storage_key,
        FileType.TXT,
        b"reviewed",
    )
    artifact = storage.verify_artifact(published)

    assert artifact.job_id == job_id
    assert artifact.storage_key == (
        f"artifacts/{job_id}/reports/reviewed/{artifact_id}.txt"
    )
    assert artifact.path == tmp_path / artifact.storage_key
    assert artifact.path.read_bytes() == b"reviewed"
    assert artifact.file_type is FileType.TXT
    assert artifact.size_bytes == 8


def test_publish_artifact_rejects_nested_symlink_escape(tmp_path) -> None:
    storage = JobStorage(tmp_path / "jobs", max_upload_bytes=1024)
    job_id = uuid4()
    artifact_id = uuid4()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = storage._root / "artifacts" / str(job_id) / "link"
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlink creation unavailable: {error}")
    storage_key = storage_module.build_artifact_storage_key(
        job_id,
        artifact_id,
        FileType.TXT,
        subdirectories=("link",),
    )

    with pytest.raises(InvalidUpload, match="reparse point"):
        storage.publish_artifact(
            job_id,
            artifact_id,
            storage_key,
            FileType.TXT,
            b"must not escape",
        )

    assert list(outside.iterdir()) == []


def test_publish_artifact_rejects_nested_reparse_component(
    tmp_path,
    monkeypatch,
) -> None:
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    job_id = uuid4()
    artifact_id = uuid4()
    storage_key = storage_module.build_artifact_storage_key(
        job_id,
        artifact_id,
        FileType.TXT,
        subdirectories=("reports",),
    )
    reparse_path = storage._root / "artifacts" / str(job_id) / "reports"
    monkeypatch.setattr(
        JobStorage,
        "_is_reparse_point",
        lambda self, path: path == reparse_path,
    )
    monkeypatch.setattr(
        JobStorage,
        "_supports_descriptor_artifact_operations",
        lambda self: False,
    )

    with pytest.raises(InvalidUpload, match="reparse point"):
        storage.publish_artifact(
            job_id,
            artifact_id,
            storage_key,
            FileType.TXT,
            b"must not escape",
        )


def test_delete_artifact_removes_only_key_owned_by_job(tmp_path) -> None:
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    job_id = uuid4()
    artifact_id = uuid4()
    storage_key = storage_module.build_artifact_storage_key(
        job_id,
        artifact_id,
        FileType.TXT,
        subdirectories=("reports", "reviewed"),
    )
    artifact = storage.publish_artifact(
        job_id,
        artifact_id,
        storage_key,
        FileType.TXT,
        b"reviewed",
    )

    assert storage.delete_artifact(job_id, storage_key) is True
    assert not artifact.path.exists()
    assert storage.delete_artifact(job_id, storage_key) is False


def test_delete_artifact_rejects_cross_job_key(tmp_path) -> None:
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    owner_job_id = uuid4()
    other_job_id = uuid4()
    storage_key = f"artifacts/{other_job_id}/{uuid4()}.txt"
    artifact_path = tmp_path / storage_key
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text("keep", encoding="utf-8")

    with pytest.raises(InvalidUpload, match="does not belong"):
        storage.delete_artifact(owner_job_id, storage_key)

    assert artifact_path.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize(
    "storage_key",
    [
        "{job_id}/source.txt",
        "compatibility/{job_id}/source.txt",
        "artifacts/{job_id}/../other/artifact.txt",
        "/absolute/artifact.txt",
        "infrastructure.env",
    ],
)
def test_artifact_storage_key_validator_rejects_non_artifact_paths(
    storage_key: str,
) -> None:
    job_id = uuid4()

    with pytest.raises(InvalidUpload):
        storage_module.validate_artifact_storage_key(
            job_id,
            storage_key.format(job_id=job_id),
        )


def test_delete_artifact_rejects_symlink_escape(tmp_path) -> None:
    storage = JobStorage(tmp_path / "jobs", max_upload_bytes=1024)
    job_id = uuid4()
    outside = tmp_path / "outside"
    outside.mkdir()
    artifact_id = uuid4()
    outside_artifact = outside / f"{artifact_id}.txt"
    outside_artifact.write_text("keep", encoding="utf-8")
    artifact_directory = storage._root / "artifacts" / str(job_id)
    artifact_directory.parent.mkdir(parents=True)
    try:
        artifact_directory.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlink creation unavailable: {error}")

    with pytest.raises(InvalidUpload, match="reparse point"):
        storage.delete_artifact(
            job_id,
            f"artifacts/{job_id}/{artifact_id}.txt",
        )

    assert outside_artifact.read_text(encoding="utf-8") == "keep"


def test_orphan_sweep_rejects_reparse_job_directory(
    tmp_path,
    monkeypatch,
    caplog,
) -> None:
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    job_id = uuid4()
    artifact_id = uuid4()
    storage_key = storage_module.build_artifact_storage_key(
        job_id,
        artifact_id,
        FileType.TXT,
    )
    artifact = storage.publish_artifact(
        job_id,
        artifact_id,
        storage_key,
        FileType.TXT,
        b"keep",
    )
    stale_timestamp = (datetime.now(UTC) - timedelta(hours=25)).timestamp()
    os.utime(artifact.path, (stale_timestamp, stale_timestamp))
    reparse_path = artifact.path.parent
    monkeypatch.setattr(
        storage,
        "_is_reparse_point",
        lambda path: path == reparse_path,
    )

    with caplog.at_level(logging.WARNING, logger="text_verification.infrastructure.storage"):
        deleted = storage.delete_orphaned_artifacts(
            set(),
            datetime.now(UTC) - timedelta(hours=24),
        )

    assert deleted == []
    assert artifact.path.read_bytes() == b"keep"
    assert [record.getMessage() for record in caplog.records] == [
        "cleanup_orphaned_artifact_delete_failed"
    ]


@pytest.mark.parametrize(
    "storage_key",
    [
        "../outside.txt",
        "exports/../../outside.txt",
        "/absolute/outside.txt",
        r"exports\..\outside.txt",
    ],
)
def test_delete_storage_key_rejects_path_traversal(
    tmp_path,
    storage_key: str,
) -> None:
    storage = JobStorage(tmp_path / "jobs", max_upload_bytes=1024)
    outside = tmp_path / "outside.txt"
    outside.write_text("keep", encoding="utf-8")

    with pytest.raises(InvalidUpload, match="storage key"):
        storage.delete_storage_key(storage_key)

    assert outside.read_text(encoding="utf-8") == "keep"


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
