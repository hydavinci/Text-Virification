from pathlib import Path
from uuid import uuid4

import pytest
from pypdf import PdfWriter

from text_verification.domain.documents import ParseError
from text_verification.parsers.pdf import PdfParser


@pytest.fixture
def fixture_path() -> Path:
    return Path(__file__).resolve().parents[2] / "fixtures" / "documents"


def test_pdf_parser_extracts_non_empty_pages(fixture_path: Path) -> None:
    document = PdfParser().parse(
        fixture_path / "sample.pdf",
        document_id=uuid4(),
        source_name="sample.pdf",
    )

    assert [block.block_id for block in document.blocks] == ["pdf-000001"]
    assert [block.kind for block in document.blocks] == ["paragraph"]
    assert [block.page for block in document.blocks] == [1]
    assert [block.text for block in document.blocks] == ["PDF sample text"]


def test_pdf_parser_rejects_encrypted_pdf(tmp_path: Path) -> None:
    source = tmp_path / "encrypted.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("secret")
    with source.open("wb") as target:
        writer.write(target)

    with pytest.raises(ParseError) as error:
        PdfParser().parse(
            source,
            document_id=uuid4(),
            source_name="encrypted.pdf",
        )

    assert error.value.code == "pdf_encrypted"
    assert error.value.public_message == "PDF 已加密，暂不支持解析。"


def test_pdf_parser_rejects_pdf_without_extractable_text(fixture_path: Path) -> None:
    with pytest.raises(ParseError) as error:
        PdfParser().parse(
            fixture_path / "blank.pdf",
            document_id=uuid4(),
            source_name="blank.pdf",
        )

    assert error.value.code == "pdf_no_extractable_text"
    assert error.value.public_message == "PDF 中没有可提取的文本，请使用包含文本层的 PDF。"
