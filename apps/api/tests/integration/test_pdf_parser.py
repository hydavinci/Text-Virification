from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest
from pydantic import ValidationError

from text_verification.document_processing.pdf_models import (
    PdfPageKind,
    PdfResourceLimits,
)
from text_verification.parsers import pdf_parser as pdf_parser_module
from text_verification.parsers.errors import ParserError, PdfResourceLimitError
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
        "pdf-page-1-line-0",
        "pdf-page-1-line-1",
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
    assert document.metadata.pdf is not None
    assert document.metadata.pdf.pages[0].kind is PdfPageKind.TEXT
    assert document.metadata.pdf.pages[0].ocr_required is False
    assert document.metadata.pdf.warnings == ()


def test_parser_marks_scanned_pages_as_ocr_required_without_running_ocr() -> None:
    document = PdfParser().parse(FIXTURE_DIRECTORY / "scanned-page.pdf")

    assert document.text == ""
    assert [block.kind for block in document.blocks] == ["image"]
    assert document.metadata.pdf is not None
    assert document.metadata.pdf.pages[0].kind is PdfPageKind.SCANNED
    assert document.metadata.pdf.pages[0].image_coverage == 1.0
    assert document.metadata.pdf.ocr_requirement is not None
    assert document.metadata.pdf.ocr_requirement.pages == (1,)


def test_parser_preserves_page_order_for_text_and_scanned_pages() -> None:
    document = PdfParser().parse(FIXTURE_DIRECTORY / "mixed-pages.pdf")

    assert [block.page for block in document.blocks] == [1, 1, 1, 1, 1, 1, 1, 2]
    assert document.metadata.pdf is not None
    assert document.metadata.pdf.pages[0].kind is PdfPageKind.TEXT
    assert document.metadata.pdf.pages[1].kind is PdfPageKind.SCANNED
    assert document.metadata.pdf.pages[1].ocr_required is True


def test_parser_preserves_native_text_on_a_mixed_page() -> None:
    document = PdfParser().parse(FIXTURE_DIRECTORY / "mixed-page.pdf")

    assert document.text == "Readable overlay text\nThis native text must not trigger OCR."
    assert document.metadata.pdf is not None
    assert document.metadata.pdf.pages[0].kind is PdfPageKind.MIXED
    assert document.metadata.pdf.pages[0].ocr_required is True


def test_parser_does_not_convert_an_unreadable_pdf_to_an_empty_document(tmp_path: Path) -> None:
    source = tmp_path / "malformed.pdf"
    source.write_bytes(b"%PDF-not-a-valid-document")

    with pytest.raises(ParserError):
        PdfParser().parse(source)


def test_parser_does_not_relabel_unexpected_open_failures_as_parse_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_failure(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("programmer failure")

    monkeypatch.setattr(pdf_parser_module._PYMUPDF, "open", unexpected_failure)

    with pytest.raises(RuntimeError, match="programmer failure"):
        PdfParser().parse(FIXTURE_DIRECTORY / "text-page.pdf")


def test_parser_records_a_deterministic_table_extraction_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_table_extraction(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise pymupdf.FileDataError("fixture table extraction failure")

    monkeypatch.setattr(pymupdf.Page, "find_tables", fail_table_extraction)

    document = PdfParser().parse(FIXTURE_DIRECTORY / "text-page.pdf")

    assert document.metadata.pdf is not None
    assert document.metadata.pdf.warnings[0].code == "pdf_table_extraction_failed"


@pytest.mark.parametrize(
    "fixture",
    ["rotated-cropped-scan-90.pdf", "rotated-cropped-scan-270.pdf"],
)
def test_parser_normalizes_rotated_cropped_image_geometry(fixture: str) -> None:
    document = PdfParser().parse(FIXTURE_DIRECTORY / fixture)

    assert document.metadata.pdf is not None
    page = document.metadata.pdf.pages[0]
    assert page.page_bbox == (0.0, 0.0, 140.0, 200.0)
    assert page.image_coverage == pytest.approx(1.0)
    assert document.blocks[0].bbox == page.page_bbox
    assert document.blocks[0].source_locator["bbox"] == [0.0, 0.0, 140.0, 200.0]


def test_parser_orders_visual_lines_and_keeps_styled_spans_on_one_line() -> None:
    document = PdfParser().parse(FIXTURE_DIRECTORY / "layout-order.pdf")

    assert document.text == "Top\nAlphaBeta\nBottom"
    assert document.blocks[0].block_id == "page-1"
    assert [
        {key: segment[key] for key in ("start", "end", "text")}
        for segment in document.blocks[0].source_locator["segments"]
    ] == [
        {"start": 0, "end": 3, "text": "Top"},
        {"start": 4, "end": 9, "text": "Alpha"},
        {"start": 9, "end": 13, "text": "Beta"},
        {"start": 14, "end": 20, "text": "Bottom"},
    ]
    for block in document.blocks:
        assert document.text[block.global_start : block.global_end] == block.text


def test_parser_preserves_complete_table_structure_without_suppressing_outside_text() -> None:
    document = PdfParser().parse(FIXTURE_DIRECTORY / "table-structure.pdf")

    assert document.metadata.pdf is not None
    table = document.metadata.pdf.pages[0].tables[0]
    assert table.row_count == 3
    assert table.column_count == 3
    assert table.rows[0][0].text == "A1\nA2"
    assert table.rows[2][2].text == ""
    assert [block.text for block in document.blocks].count("B1") == 2
    assert sum(block.kind == "table_cell" for block in document.blocks) == 2


def test_parser_enforces_page_limit_before_extracting_pages() -> None:
    with pytest.raises(PdfResourceLimitError) as raised:
        PdfParser(limits=PdfResourceLimits(max_pages=1)).parse(
            FIXTURE_DIRECTORY / "mixed-pages.pdf"
        )

    assert raised.value.limit == "max_pages"
    assert raised.value.maximum == 1
    assert raised.value.actual == 2


@pytest.mark.parametrize(
    ("fixture", "limits", "limit"),
    [
        (
            "two-images.pdf",
            PdfResourceLimits(max_images_per_page=1),
            "max_images_per_page",
        ),
        (
            "two-images.pdf",
            PdfResourceLimits(max_image_xrefs_per_page=1),
            "max_image_xrefs_per_page",
        ),
        (
            "repeated-image.pdf",
            PdfResourceLimits(max_image_rectangles_per_page=1),
            "max_image_rectangles_per_page",
        ),
        (
            "table-structure.pdf",
            PdfResourceLimits(max_table_cells_per_page=8),
            "max_table_cells_per_page",
        ),
    ],
)
def test_parser_enforces_per_page_resource_limits(
    fixture: str,
    limits: PdfResourceLimits,
    limit: str,
) -> None:
    with pytest.raises(PdfResourceLimitError) as raised:
        PdfParser(limits=limits).parse(FIXTURE_DIRECTORY / fixture)

    assert raised.value.limit == limit


def test_table_library_failure_is_recoverable_but_validation_failure_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def library_failure(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise pymupdf.FileDataError("corrupt table structures")

    monkeypatch.setattr(pymupdf.Page, "find_tables", library_failure)
    document = PdfParser().parse(FIXTURE_DIRECTORY / "text-page.pdf")
    assert document.metadata.pdf is not None
    assert document.metadata.pdf.warnings[0].stage == "table"

    def validation_failure(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise ValidationError.from_exception_data("PdfTable", [])

    monkeypatch.setattr(pymupdf.Page, "find_tables", validation_failure)
    with pytest.raises(ValidationError):
        PdfParser().parse(FIXTURE_DIRECTORY / "text-page.pdf")


def test_image_library_failure_is_recoverable_but_validation_failure_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def library_failure(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise pymupdf.FileDataError("corrupt image structures")

    monkeypatch.setattr(pymupdf.Page, "get_images", library_failure)
    document = PdfParser().parse(FIXTURE_DIRECTORY / "text-page.pdf")
    assert document.metadata.pdf is not None
    assert document.metadata.pdf.warnings[0].stage == "image"

    def validation_failure(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise ValidationError.from_exception_data("PdfImage", [])

    monkeypatch.setattr(pymupdf.Page, "get_images", validation_failure)
    with pytest.raises(ValidationError):
        PdfParser().parse(FIXTURE_DIRECTORY / "text-page.pdf")
