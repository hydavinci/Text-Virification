from pathlib import Path
from uuid import uuid4

import pytest
from pypdf import PdfReader, PdfWriter

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


def test_pdf_parser_normalizes_extract_text_exceptions(
    fixture_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page_type = type(PdfReader(str(fixture_path / "sample.pdf")).pages[0])

    def raising_extract_text(self: object, *args: object, **kwargs: object) -> str:
        del self, args, kwargs
        raise RuntimeError("boom")

    monkeypatch.setattr(page_type, "extract_text", raising_extract_text)

    with pytest.raises(ParseError) as error:
        PdfParser().parse(
            fixture_path / "sample.pdf",
            document_id=uuid4(),
            source_name="sample.pdf",
        )

    assert error.value.code == "pdf_text_extraction_failed"
    assert (
        error.value.public_message
        == "无法提取 PDF 文本，请检查文件是否损坏或是否包含受支持的文本层。"
    )


def test_pdf_parser_normalizes_non_string_extract_text_results(
    fixture_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page_type = type(PdfReader(str(fixture_path / "sample.pdf")).pages[0])

    def invalid_extract_text(self: object, *args: object, **kwargs: object) -> object:
        del self, args, kwargs
        return 123

    monkeypatch.setattr(page_type, "extract_text", invalid_extract_text)

    with pytest.raises(ParseError) as error:
        PdfParser().parse(
            fixture_path / "sample.pdf",
            document_id=uuid4(),
            source_name="sample.pdf",
        )

    assert error.value.code == "pdf_text_extraction_failed"
    assert (
        error.value.public_message
        == "无法提取 PDF 文本，请检查文件是否损坏或是否包含受支持的文本层。"
    )
