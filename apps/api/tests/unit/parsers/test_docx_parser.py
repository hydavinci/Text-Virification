from pathlib import Path
from uuid import uuid4

import pytest

from text_verification.domain.documents import ParseError
from text_verification.parsers.docx import DocxParser


@pytest.fixture
def fixture_path() -> Path:
    return Path(__file__).resolve().parents[2] / "fixtures" / "documents"


def test_docx_parser_preserves_paragraph_table_and_run_mapping(fixture_path: Path) -> None:
    document = DocxParser().parse(
        fixture_path / "sample.docx",
        document_id=uuid4(),
        source_name="sample.docx",
    )

    assert [block.block_id for block in document.blocks] == [
        "h-000001",
        "p-000001",
        "t-000001-000001",
        "t-000001-000002",
    ]
    assert [block.kind for block in document.blocks] == [
        "heading",
        "paragraph",
        "table_cell",
        "table_cell",
    ]
    paragraph = document.blocks[1]
    assert paragraph.text == "核验示例文本"
    assert paragraph.source_locator["runs"] == [
        {"run_index": 0, "start": 0, "end": 2},
        {"run_index": 1, "start": 2, "end": 6},
    ]


def test_docx_parser_rejects_missing_document_xml(tmp_path: Path) -> None:
    source = tmp_path / "broken.docx"
    source.write_bytes(b"not-a-docx")

    with pytest.raises(ParseError, match="无法解析 DOCX 文件"):
        DocxParser().parse(source, document_id=uuid4(), source_name="broken.docx")
