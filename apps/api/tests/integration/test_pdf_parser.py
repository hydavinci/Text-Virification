from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from text_verification.document_processing.pdf_models import PdfPageKind
from text_verification.parsers.errors import ParserError
from text_verification.parsers.pdf_parser import PdfParser

FIXTURE_DIRECTORY = Path(__file__).resolve().parents[1] / "fixtures" / "pdf"


def test_parser_extracts_ordered_text_table_and_image_blocks() -> None:
    document = PdfParser().parse(FIXTURE_DIRECTORY / "text-page.pdf")

    assert document.parser_name == "pymupdf-pdf"
    assert document.parser_version
    assert document.text == (
        "Structured text page\nThis page has a useful text layer.\nA1\nB1\nA2\nB2"
    )
    assert [block.block_id for block in document.blocks] == [
        "pdf-page-1-paragraph-0",
        "pdf-page-1-paragraph-1",
        "pdf-page-1-table-0-row-0-cell-0",
        "pdf-page-1-table-0-row-0-cell-1",
        "pdf-page-1-table-0-row-1-cell-0",
        "pdf-page-1-table-0-row-1-cell-1",
        "pdf-page-1-image-0",
    ]
    assert [block.kind for block in document.blocks] == [
        "paragraph",
        "paragraph",
        "table_cell",
        "table_cell",
        "table_cell",
        "table_cell",
        "image",
    ]
    assert document.blocks[-1].text == ""
    assert document.blocks[-1].source_locator == {
        "locator_kind": "image",
        "page": 1,
        "image_index": 0,
        "xref": document.blocks[-1].source_locator["xref"],
        "bbox": [200.0, 200.0, 220.0, 220.0],
    }
    assert [block.global_start for block in document.blocks] == [0, 21, 56, 59, 62, 65, 67]
    assert document.blocks[0].style["font"] == {
        "name": "Helvetica",
        "size": 12.0,
        "flags": 0,
        "color": 0,
    }
    assert [
        block.source_locator["page"] for block in document.blocks
    ] == [1, 1, 1, 1, 1, 1, 1]
    assert document.metadata["pdf"]["pages"][0]["kind"] == PdfPageKind.TEXT.value
    assert document.metadata["pdf"]["pages"][0]["ocr_required"] is False
    assert document.metadata["pdf"]["warnings"] == []


def test_parser_marks_scanned_pages_as_ocr_required_without_running_ocr() -> None:
    document = PdfParser().parse(FIXTURE_DIRECTORY / "scanned-page.pdf")

    assert document.text == ""
    assert [block.kind for block in document.blocks] == ["image"]
    assert document.metadata["pdf"]["pages"] == [
        {
            "page": 1,
            "kind": PdfPageKind.SCANNED.value,
            "text_length": 0,
            "text_density": 0.0,
            "image_coverage": 1.0,
            "ocr_required": True,
        }
    ]


def test_parser_preserves_page_order_for_text_and_scanned_pages() -> None:
    document = PdfParser().parse(FIXTURE_DIRECTORY / "mixed-pages.pdf")

    assert [block.page for block in document.blocks] == [1, 1, 1, 1, 1, 1, 1, 2]
    assert document.metadata["pdf"]["pages"][0]["kind"] == PdfPageKind.TEXT.value
    assert document.metadata["pdf"]["pages"][1]["kind"] == PdfPageKind.SCANNED.value
    assert document.metadata["pdf"]["pages"][1]["ocr_required"] is True


def test_parser_preserves_native_text_on_a_mixed_page() -> None:
    document = PdfParser().parse(FIXTURE_DIRECTORY / "mixed-page.pdf")

    assert document.text == "Readable overlay text\nThis native text must not trigger OCR."
    assert document.metadata["pdf"]["pages"][0]["kind"] == PdfPageKind.MIXED.value
    assert document.metadata["pdf"]["pages"][0]["ocr_required"] is True


def test_parser_does_not_convert_an_unreadable_pdf_to_an_empty_document(tmp_path: Path) -> None:
    source = tmp_path / "malformed.pdf"
    source.write_bytes(b"%PDF-not-a-valid-document")

    with pytest.raises(ParserError):
        PdfParser().parse(source)


def test_parser_records_a_deterministic_table_extraction_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_table_extraction(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("fixture table extraction failure")

    monkeypatch.setattr(pymupdf.Page, "find_tables", fail_table_extraction)

    document = PdfParser().parse(FIXTURE_DIRECTORY / "text-page.pdf")

    assert document.metadata["pdf"]["warnings"] == [
        {
            "page": 1,
            "stage": "table",
            "code": "pdf_table_extraction_failed",
            "message": "PyMuPDF table extraction failed.",
        }
    ]
