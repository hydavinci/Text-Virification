import hashlib
from pathlib import Path

from text_verification.compatibility.adapters import (
    parsed_file_to_document_model,
    source_version_for_file,
)
from text_verification.domain.documents import FileType


def test_uploaded_document_preserves_source_byte_version_verbatim() -> None:
    document = parsed_file_to_document_model(
        text="normalized extracted text",
        source_version="source-revision:immutable-upload",
        source_name="source.txt",
        file_type=FileType.TXT,
        parser_name="compatibility-txt",
        page_map=[],
    )

    assert document.source_version == "source-revision:immutable-upload"


def test_source_version_for_file_hashes_immutable_bytes(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_bytes("帐号".encode("utf-16"))

    version = source_version_for_file(source)

    assert version == f"sha256:{hashlib.sha256(source.read_bytes()).hexdigest()}"
