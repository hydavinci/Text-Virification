from pathlib import Path
from uuid import UUID, uuid4

import pytest

from text_verification.domain.documents import FileType, ParseError
from text_verification.parsers.registry import ParserRegistry
from text_verification.parsers.txt import TxtParser


def test_txt_parser_normalizes_bom_and_line_endings(tmp_path: Path) -> None:
    source = tmp_path / "sample.txt"
    source.write_bytes(b"\xef\xbb\xbf\xe7\xac\xac\xe4\xb8\x80\xe8\xa1\x8c\r\n\r\n\xe7\xac\xac\xe4\xba\x8c\xe8\xa1\x8c")

    document = TxtParser().parse(
        source,
        document_id=UUID("00000000-0000-0000-0000-000000000001"),
        source_name="sample.txt",
    )

    assert [block.block_id for block in document.blocks] == ["p-000001", "p-000002"]
    assert [block.text for block in document.blocks] == ["第一行", "第二行"]
    assert document.metadata["encoding"] == "utf-8-sig"


def test_txt_parser_decodes_gb18030_content(tmp_path: Path) -> None:
    source = tmp_path / "sample.txt"
    source.write_bytes("仅 GB18030".encode("gb18030"))

    document = TxtParser().parse(
        source,
        document_id=uuid4(),
        source_name="sample.txt",
    )

    assert [block.block_id for block in document.blocks] == ["p-000001"]
    assert [block.text for block in document.blocks] == ["仅 GB18030"]
    assert document.metadata["encoding"] == "gb18030"


def test_txt_parser_rejects_binary_content(tmp_path: Path) -> None:
    source = tmp_path / "sample.txt"
    source.write_bytes(b"\x00\x01\x02")

    with pytest.raises(ParseError, match="无法解析文本文件"):
        TxtParser().parse(source, document_id=uuid4(), source_name="sample.txt")


def test_registry_returns_txt_parser_and_rejects_missing_types() -> None:
    registry = ParserRegistry([TxtParser()])

    assert registry.get(FileType.TXT).supported_type is FileType.TXT

    with pytest.raises(ParseError) as error:
        registry.get(FileType.PDF)

    assert error.value.code == "unsupported_parser"
    assert error.value.public_message == "暂不支持解析该文件类型。"
