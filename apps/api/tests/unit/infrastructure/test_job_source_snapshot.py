from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest

from text_verification.domain.documents import DocumentModel, FileType, TextBlock
from text_verification.infrastructure.storage import (
    InvalidUpload,
    JobOwnedSourcePathResolver,
    JobStorage,
)


@pytest.mark.parametrize("file_type", list(FileType))
def test_verified_source_copy_is_immutable_for_all_seven_formats(
    tmp_path: Path,
    file_type: FileType,
) -> None:
    storage = JobStorage(tmp_path / "jobs", max_upload_bytes=1024)
    job_id = uuid4()
    source = _write_source(storage, job_id, file_type, b"original source")
    resolver = JobOwnedSourcePathResolver(storage, job_id, file_type)
    document = _document(job_id, file_type, b"original source")

    with resolver.open_verified_copy(document) as verified:
        assert verified != source
        assert verified.read_bytes() == b"original source"
        source.write_bytes(b"tampered after verification")
        assert verified.read_bytes() == b"original source"
        verified_path = verified

    assert not verified_path.exists()
    assert not verified_path.parent.exists()


def test_verified_source_copy_rejects_tampered_bytes_before_copying(
    tmp_path: Path,
) -> None:
    storage = JobStorage(tmp_path / "jobs", max_upload_bytes=1024)
    job_id = uuid4()
    source = _write_source(storage, job_id, FileType.TXT, b"original source")
    document = _document(job_id, FileType.TXT, b"original source")
    source.write_bytes(b"tampered before verification")

    with pytest.raises(InvalidUpload, match="canonical source version"):
        with JobOwnedSourcePathResolver(
            storage,
            job_id,
            FileType.TXT,
        ).open_verified_copy(document):
            pass


def test_verified_source_copy_rejects_a_symlinked_source_leaf(
    tmp_path: Path,
) -> None:
    storage = JobStorage(tmp_path / "jobs", max_upload_bytes=1024)
    job_id = uuid4()
    source = _write_source(storage, job_id, FileType.TXT, b"original source")
    document = _document(job_id, FileType.TXT, b"original source")
    target = tmp_path / "outside.txt"
    target.write_bytes(b"original source")
    source.unlink()
    source.symlink_to(target)

    with pytest.raises(InvalidUpload, match="unsafe|reparse point"):
        with JobOwnedSourcePathResolver(
            storage,
            job_id,
            FileType.TXT,
        ).open_verified_copy(document):
            pass


def _write_source(
    storage: JobStorage,
    job_id,
    file_type: FileType,
    content: bytes,
) -> Path:
    directory = storage.job_directory(job_id)
    directory.mkdir(parents=True)
    source = directory / f"source.{file_type.value}"
    source.write_bytes(content)
    return source


def _document(
    job_id,
    file_type: FileType,
    source_bytes: bytes,
) -> DocumentModel:
    text = "source"
    return DocumentModel(
        document_id=job_id,
        source_version=f"sha256:{sha256(source_bytes).hexdigest()}",
        file_type=file_type,
        source_name=f"sample.{file_type.value}",
        text=text,
        blocks=[
            TextBlock(
                block_id="p-0",
                kind="paragraph",
                text=text,
                global_start=0,
                global_end=len(text),
                block_start=0,
                block_end=len(text),
                page=None,
                paragraph_index=0,
                table_index=None,
                row_index=None,
                cell_index=None,
                bbox=None,
                parent_id=None,
                style={},
                source_locator={"paragraph_index": 0},
            )
        ],
        parser_name="test",
        parser_version="1",
    )
