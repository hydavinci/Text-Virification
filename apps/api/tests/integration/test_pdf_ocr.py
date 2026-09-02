from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pymupdf
import pytest

from text_verification.application.verification_pipeline import (
    VerificationCommand,
    VerificationPipeline,
)
from text_verification.checkers.compatibility_checker import CompatibilityChecker
from text_verification.checkers.registry import CheckerRegistry
from text_verification.document_processing.errors import OcrOutputError, OcrUnavailableError
from text_verification.document_processing.layout import OcrLayoutBox, OcrLayoutElement
from text_verification.document_processing.ocr_provider import OcrTextBox
from text_verification.document_processing.pdf_models import (
    PdfPageKind,
    PdfPageMetadata,
    PdfResourceLimits,
    PdfTable,
    PdfTableCell,
    PdfTextSpan,
)
from text_verification.domain.documents import DocumentModel, FileType
from text_verification.domain.verification import (
    VerificationExecutionMode,
    VerificationOptions,
)
from text_verification.parsers import pdf_parser as pdf_parser_module
from text_verification.parsers.errors import PdfResourceLimitError
from text_verification.parsers.pdf_parser import PdfParser
from text_verification.parsers.registry import ParserRegistry

FIXTURE_DIRECTORY = Path(__file__).resolve().parents[1] / "fixtures" / "pdf"


def _ocr_box(
    text: str,
    bbox: tuple[float, float, float, float],
    *,
    confidence: float = 0.9,
) -> OcrTextBox:
    x0, y0, x1, y1 = bbox
    return OcrTextBox(
        text=text,
        confidence=confidence,
        bbox=((x0, y0), (x1, y0), (x1, y1), (x0, y1)),
    )


def _layout_box(
    text: str,
    bbox: tuple[float, float, float, float],
    *,
    confidence: float = 0.9,
    index: int = 0,
) -> OcrLayoutBox:
    x0, y0, x1, y1 = bbox
    return OcrLayoutBox(
        page=1,
        box_index=index,
        text=text,
        confidence=confidence,
        quad=((x0, y0), (x1, y0), (x1, y1), (x0, y1)),
    )


def _native_span(
    text: str,
    bbox: tuple[float, float, float, float],
    *,
    span_index: int = 0,
) -> PdfTextSpan:
    return PdfTextSpan(
        text=text,
        bbox=bbox,
        font_name="Helvetica",
        font_size=10.0,
        font_flags=0,
        color=0,
        span_index=span_index,
    )


class FakeOcr:
    def __init__(self, outputs: list[list[OcrTextBox]]) -> None:
        self._outputs = iter(outputs)
        self.calls: list[tuple[object, str]] = []

    def recognize(self, image: object, language: str) -> list[OcrTextBox]:
        self.calls.append((image, language))
        return next(self._outputs)


def _scanned_table_output() -> list[OcrTextBox]:
    return [
        _ocr_box("A1", (48.0, 48.0, 96.0, 70.0), confidence=0.99),
        _ocr_box("B1", (250.0, 48.0, 300.0, 70.0), confidence=0.98),
        _ocr_box("A2", (48.0, 120.0, 96.0, 142.0), confidence=0.97),
        _ocr_box("B2", (250.0, 120.0, 300.0, 142.0), confidence=0.96),
    ]


def _mixed_table_pdf(target: Path) -> Path:
    with pymupdf.open(FIXTURE_DIRECTORY / "scanned-page.pdf") as scan:
        xref = scan[0].get_images(full=True)[0][0]
        background = scan.extract_image(xref)["image"]

    document = pymupdf.open()
    page = document.new_page(width=240, height=240)
    page.insert_image(page.rect, stream=background)
    x0, y0, width, height = 24.0, 60.0, 80.0, 28.0
    for column in range(3):
        x = x0 + column * width
        page.draw_line((x, y0), (x, y0 + height * 2))
    for row in range(3):
        y = y0 + row * height
        page.draw_line((x0, y), (x0 + width * 2, y))
    for text, x, y in (
        ("A1", 34.0, 78.0),
        ("B1", 114.0, 78.0),
        ("A2", 34.0, 106.0),
        ("B2", 114.0, 106.0),
    ):
        page.insert_text((x, y), text, fontsize=10, fontname="helv")
    page.insert_text((24.0, 30.0), "Native heading", fontsize=12, fontname="helv")
    document.save(target)
    document.close()
    return target


def test_two_page_text_and_scan_uses_ocr_only_for_required_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rendered_pages: list[int] = []
    original = pdf_parser_module._render_page_for_ocr

    def recording_render(page: pymupdf.Page, limits: PdfResourceLimits):
        rendered_pages.append(page.number + 1)
        return original(page, limits)

    monkeypatch.setattr(pdf_parser_module, "_render_page_for_ocr", recording_render)
    ocr = FakeOcr([[_ocr_box("OCR page text", (48.0, 48.0, 250.0, 76.0))]])

    document = PdfParser(ocr=ocr).parse(FIXTURE_DIRECTORY / "mixed-pages.pdf")

    assert rendered_pages == [2]
    assert len(ocr.calls) == 1
    assert [block.page for block in document.blocks if block.text][-1] == 2
    assert document.text.endswith("\nOCR page text")
    assert document.metadata.pdf is not None
    assert document.metadata.pdf.ocr_requirement is None
    assert document.metadata.pdf.pages[1].ocr_required is False
    assert document.metadata.pdf.pages[0].kind is PdfPageKind.TEXT


def test_text_page_never_calls_or_initializes_ocr() -> None:
    class FailingOcr:
        def recognize(self, image: object, language: str) -> list[OcrTextBox]:
            del image, language
            raise AssertionError("native text pages must not invoke OCR")

    document = PdfParser(ocr=FailingOcr()).parse(FIXTURE_DIRECTORY / "text-page.pdf")

    assert document.text.startswith("Structured text page")


def test_genuine_mixed_page_preserves_native_table_and_deduplicates_overlay(
    tmp_path: Path,
) -> None:
    source = _mixed_table_pdf(tmp_path / "mixed-table.pdf")
    ocr = FakeOcr(
        [[
            _ocr_box("Native heading", (44.0, 34.0, 310.0, 68.0)),
            _ocr_box("Unique scan note", (48.0, 340.0, 240.0, 370.0)),
        ]]
    )

    document = PdfParser(ocr=ocr).parse(source)

    assert document.metadata.pdf is not None
    assert document.metadata.pdf.pages[0].kind is PdfPageKind.MIXED
    assert document.metadata.pdf.ocr_requirement is None
    assert document.text.count("Native heading") == 1
    assert document.text.endswith("Unique scan note")
    assert [block.text for block in document.blocks if block.kind == "table_cell"] == [
        "A1",
        "B1",
        "A2",
        "B2",
    ]
    assert any(block.kind == "image" for block in document.blocks)


def test_mixed_page_offsets_ocr_paragraph_indices_after_native_paragraphs() -> None:
    output = [_ocr_box("Unique scan note", (48.0, 340.0, 240.0, 370.0))]
    first = PdfParser(ocr=FakeOcr([output])).parse(FIXTURE_DIRECTORY / "mixed-page.pdf")
    second = PdfParser(ocr=FakeOcr([output])).parse(FIXTURE_DIRECTORY / "mixed-page.pdf")
    native = [
        block
        for block in first.blocks
        if block.kind == "paragraph" and block.source_locator["locator_kind"] == "pdf_line"
    ]
    ocr_block = next(block for block in first.blocks if block.text == "Unique scan note")

    assert [block.paragraph_index for block in native] == [0, 1]
    assert ocr_block.paragraph_index == 2
    assert ocr_block.block_id == "ocr-page-1-paragraph-2"
    assert ocr_block.source_locator["paragraph_index"] == 2
    assert len({block.paragraph_index for block in (*native, ocr_block)}) == 3
    assert [block.block_id for block in first.blocks] == [
        block.block_id for block in second.blocks
    ]
    assert DocumentModel.model_validate_json(first.model_dump_json()) == first


def test_mixed_page_offsets_ocr_table_index_and_keeps_local_row_cell_indices(
    tmp_path: Path,
) -> None:
    source = _mixed_table_pdf(tmp_path / "native-and-ocr-tables.pdf")
    ocr = FakeOcr(
        [[
            _ocr_box("C1", (48.0, 300.0, 96.0, 322.0), confidence=0.99),
            _ocr_box("D1", (250.0, 300.0, 300.0, 322.0), confidence=0.98),
            _ocr_box("C2", (48.0, 350.0, 96.0, 372.0), confidence=0.97),
            _ocr_box("D2", (250.0, 350.0, 300.0, 372.0), confidence=0.96),
        ]]
    )

    document = PdfParser(ocr=ocr).parse(source)
    native_cells = [
        block
        for block in document.blocks
        if block.kind == "table_cell" and block.source_locator["locator_kind"] == "table_cell"
    ]
    ocr_cells = [
        block
        for block in document.blocks
        if block.kind == "table_cell" and block.source_locator.get("source") == "ocr"
    ]

    assert {cell.table_index for cell in native_cells} == {0}
    assert [
        (cell.table_index, cell.row_index, cell.cell_index, cell.text)
        for cell in ocr_cells
    ] == [
        (1, 0, 0, "C1"),
        (1, 0, 1, "D1"),
        (1, 1, 0, "C2"),
        (1, 1, 1, "D2"),
    ]
    assert [cell.block_id for cell in ocr_cells] == [
        "ocr-page-1-table-1-row-0-cell-0",
        "ocr-page-1-table-1-row-0-cell-1",
        "ocr-page-1-table-1-row-1-cell-0",
        "ocr-page-1-table-1-row-1-cell-1",
    ]
    assert all(cell.source_locator["table_index"] == 1 for cell in ocr_cells)
    assert len({cell.block_id for cell in document.blocks}) == len(document.blocks)
    assert DocumentModel.model_validate_json(document.model_dump_json()) == document


def test_ocr_table_index_offsets_after_structural_native_empty_table() -> None:
    empty_cell = PdfTableCell(
        text="",
        bbox=(10.0, 10.0, 30.0, 30.0),
        table_index=3,
        row_index=0,
        cell_index=0,
    )
    page = PdfPageMetadata(
        page=1,
        kind=PdfPageKind.MIXED,
        page_bbox=(0.0, 0.0, 200.0, 200.0),
        text_length=0,
        text_density=0.0,
        image_coverage=1.0,
        ocr_required=False,
        tables=(
            PdfTable(
                table_index=3,
                bbox=(10.0, 10.0, 30.0, 30.0),
                row_count=1,
                column_count=1,
                rows=((empty_cell,),),
            ),
        ),
    )
    box = _layout_box("OCR", (50.0, 50.0, 80.0, 65.0))
    element = OcrLayoutElement(
        kind="table_cell",
        page=1,
        text="OCR",
        bbox=box.bbox,
        confidence=box.confidence,
        language="en",
        table_index=0,
        row_index=0,
        cell_index=0,
        boxes=(box,),
    )

    blocks, _ = pdf_parser_module._canonical_blocks(
        (page,),
        ocr_elements_by_page={1: (element,)},
    )
    ocr_block = next(block for block in blocks if block.text == "OCR")

    assert ocr_block.table_index == 4
    assert ocr_block.block_id == "ocr-page-1-table-4-row-0-cell-0"


def test_scanned_table_preserves_rows_cells_confidence_and_json_persistence() -> None:
    first = PdfParser(ocr=FakeOcr([_scanned_table_output()])).parse(
        FIXTURE_DIRECTORY / "scanned-table.pdf"
    )
    second = PdfParser(ocr=FakeOcr([_scanned_table_output()])).parse(
        FIXTURE_DIRECTORY / "scanned-table.pdf"
    )
    cells = [block for block in first.blocks if block.kind == "table_cell"]

    assert [(cell.row_index, cell.cell_index, cell.text) for cell in cells] == [
        (0, 0, "A1"),
        (0, 1, "B1"),
        (1, 0, "A2"),
        (1, 1, "B2"),
    ]
    assert all(cell.table_index == 0 for cell in cells)
    assert [cell.source_locator["confidence"] for cell in cells] == [
        0.99,
        0.98,
        0.97,
        0.96,
    ]
    assert all(cell.source_locator["source"] == "ocr" for cell in cells)
    assert all(cell.source_locator["language"] == "zh" for cell in cells)
    assert [block.block_id for block in first.blocks] == [
        block.block_id for block in second.blocks
    ]
    restored = DocumentModel.model_validate_json(first.model_dump_json())
    assert restored == first
    assert all(first.text[cell.global_start : cell.global_end] == cell.text for cell in cells)


@pytest.mark.parametrize(
    ("fixture", "pixel_bbox", "expected_page_bbox", "expected_block_bbox"),
    [
        (
            "rotated-cropped-scan-0.pdf",
            (40.0, 28.0, 120.0, 56.0),
            (0.0, 0.0, 200.0, 140.0),
            (20.0, 14.0, 60.0, 28.0),
        ),
        (
            "rotated-cropped-scan-90.pdf",
            (28.0, 40.0, 84.0, 80.0),
            (0.0, 0.0, 140.0, 200.0),
            (14.0, 20.0, 42.0, 40.0),
        ),
        (
            "rotated-cropped-scan-180.pdf",
            (40.0, 28.0, 120.0, 56.0),
            (0.0, 0.0, 200.0, 140.0),
            (20.0, 14.0, 60.0, 28.0),
        ),
        (
            "rotated-cropped-scan-270.pdf",
            (28.0, 40.0, 84.0, 80.0),
            (0.0, 0.0, 140.0, 200.0),
            (14.0, 20.0, 42.0, 40.0),
        ),
    ],
)
def test_rotated_cropped_ocr_coordinates_map_to_visual_pdf_space(
    fixture: str,
    pixel_bbox: tuple[float, float, float, float],
    expected_page_bbox: tuple[float, float, float, float],
    expected_block_bbox: tuple[float, float, float, float],
) -> None:
    ocr = FakeOcr([[_ocr_box("Rotated", pixel_bbox)]])

    document = PdfParser(ocr=ocr).parse(FIXTURE_DIRECTORY / fixture)
    block = next(block for block in document.blocks if block.text == "Rotated")

    assert document.metadata.pdf is not None
    assert document.metadata.pdf.pages[0].page_bbox == expected_page_bbox
    assert block.bbox == pytest.approx(expected_block_bbox)
    assert block.source_locator["quad"] == [
        [expected_block_bbox[0], expected_block_bbox[1]],
        [expected_block_bbox[2], expected_block_bbox[1]],
        [expected_block_bbox[2], expected_block_bbox[3]],
        [expected_block_bbox[0], expected_block_bbox[3]],
    ]


@pytest.mark.parametrize(
    "raw_box",
    [
        {
            "text": "bool",
            "confidence": 0.9,
            "bbox": ((True, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)),
        },
        {
            "text": "nan",
            "confidence": 0.9,
            "bbox": ((math.nan, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)),
        },
        {
            "text": "inf",
            "confidence": 0.9,
            "bbox": ((0.0, 0.0), (math.inf, 0.0), (10.0, 10.0), (0.0, 10.0)),
        },
        {
            "text": "degenerate",
            "confidence": 0.9,
            "bbox": ((0.0, 0.0), (10.0, 0.0), (20.0, 0.0), (30.0, 0.0)),
        },
        OcrTextBox(
            text="outside",
            confidence=0.9,
            bbox=((0.0, 0.0), (481.0, 0.0), (481.0, 10.0), (0.0, 10.0)),
        ),
    ],
)
def test_parser_boundary_rejects_invalid_ocr_geometry_as_output_error(
    raw_box: object,
) -> None:
    class MalformedGeometryOcr:
        def recognize(self, image: object, language: str) -> list[OcrTextBox]:
            del image, language
            return [raw_box]  # type: ignore[list-item]

    with pytest.raises(OcrOutputError):
        PdfParser(ocr=MalformedGeometryOcr()).parse(FIXTURE_DIRECTORY / "scanned-page.pdf")


def test_parser_accepts_ocr_geometry_exactly_on_rendered_boundaries() -> None:
    ocr = FakeOcr(
        [[
            OcrTextBox(
                text="Boundary",
                confidence=0.9,
                bbox=((0.0, 0.0), (480.0, 0.0), (480.0, 20.0), (0.0, 20.0)),
            )
        ]]
    )

    document = PdfParser(ocr=ocr).parse(FIXTURE_DIRECTORY / "scanned-page.pdf")
    block = next(block for block in document.blocks if block.text == "Boundary")

    assert block.bbox == (0.0, 0.0, 240.0, 10.0)


def test_empty_ocr_keeps_typed_requirement_and_records_warning() -> None:
    document = PdfParser(ocr=FakeOcr([[]])).parse(FIXTURE_DIRECTORY / "scanned-page.pdf")

    assert document.metadata.pdf is not None
    assert document.metadata.pdf.ocr_requirement is not None
    assert document.metadata.pdf.ocr_requirement.mode == "required"
    assert document.metadata.pdf.ocr_requirement.pages == (1,)
    assert document.metadata.pdf.warnings[-1].stage == "ocr"
    assert document.metadata.pdf.warnings[-1].code == "pdf_ocr_no_text"


def test_duplicate_only_mixed_ocr_stays_partial_and_warns() -> None:
    ocr = FakeOcr(
        [[_ocr_box("Readable overlay text", (44.0, 34.0, 310.0, 68.0))]]
    )

    document = PdfParser(ocr=ocr).parse(FIXTURE_DIRECTORY / "mixed-page.pdf")

    assert document.metadata.pdf is not None
    assert document.metadata.pdf.ocr_requirement is not None
    assert document.metadata.pdf.ocr_requirement.mode == "partial"
    assert document.metadata.pdf.ocr_requirement.pages == (1,)
    assert document.metadata.pdf.pages[0].ocr_required is True
    assert document.metadata.pdf.warnings[-1].code == "pdf_ocr_no_text"
    assert document.text.count("Readable overlay text") == 1


def test_nonempty_provider_output_with_empty_layout_stays_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pdf_parser_module,
        "build_ocr_layout",
        lambda *args, **kwargs: SimpleNamespace(elements=()),
    )
    ocr = FakeOcr([[_ocr_box("Recognized", (48.0, 48.0, 200.0, 76.0))]])

    document = PdfParser(ocr=ocr).parse(FIXTURE_DIRECTORY / "scanned-page.pdf")

    assert document.metadata.pdf is not None
    assert document.metadata.pdf.ocr_requirement is not None
    assert document.metadata.pdf.ocr_requirement.mode == "required"
    assert document.metadata.pdf.pages[0].ocr_required is True
    assert document.metadata.pdf.warnings[-1].code == "pdf_ocr_no_text"


def test_zero_confidence_scan_stays_required_and_emits_warning() -> None:
    document = PdfParser(
        ocr=FakeOcr(
            [[_ocr_box("Unusable", (48.0, 48.0, 200.0, 76.0), confidence=0.0)]]
        )
    ).parse(FIXTURE_DIRECTORY / "scanned-page.pdf")

    assert document.text == ""
    assert document.metadata.pdf is not None
    assert document.metadata.pdf.ocr_requirement is not None
    assert document.metadata.pdf.ocr_requirement.mode == "required"
    assert document.metadata.pdf.pages[0].ocr_required is True
    assert document.metadata.pdf.warnings[-1].code == "pdf_ocr_no_text"


def test_zero_confidence_mixed_page_stays_partial() -> None:
    document = PdfParser(
        ocr=FakeOcr(
            [[_ocr_box("Unique but unusable", (48.0, 340.0, 260.0, 370.0), confidence=0.0)]]
        )
    ).parse(FIXTURE_DIRECTORY / "mixed-page.pdf")

    assert document.text == "Readable overlay text\nThis native text must not trigger OCR."
    assert document.metadata.pdf is not None
    assert document.metadata.pdf.ocr_requirement is not None
    assert document.metadata.pdf.ocr_requirement.mode == "partial"
    assert document.metadata.pdf.warnings[-1].code == "pdf_ocr_no_text"


def test_mixed_usable_and_zero_confidence_keeps_only_usable_confidence() -> None:
    document = PdfParser(
        ocr=FakeOcr(
            [[
                _ocr_box("Usable", (48.0, 340.0, 160.0, 370.0), confidence=0.4),
                _ocr_box("Discard", (48.0, 380.0, 180.0, 410.0), confidence=0.0),
            ]]
        )
    ).parse(FIXTURE_DIRECTORY / "mixed-page.pdf")
    ocr_blocks = [
        block
        for block in document.blocks
        if block.source_locator.get("source") == "ocr"
    ]

    assert [block.text for block in ocr_blocks] == ["Usable"]
    assert ocr_blocks[0].source_locator["confidence"] == 0.4
    assert len(ocr_blocks[0].source_locator["boxes"]) == 1
    assert document.metadata.pdf is not None
    assert document.metadata.pdf.ocr_requirement is None


def test_minimum_usable_confidence_policy_is_named_and_exact() -> None:
    threshold = pdf_parser_module.MIN_USABLE_OCR_CONFIDENCE

    assert 0.0 < threshold <= 0.05
    accepted = PdfParser(
        ocr=FakeOcr(
            [[_ocr_box("Accepted", (48.0, 48.0, 200.0, 76.0), confidence=threshold)]]
        )
    ).parse(FIXTURE_DIRECTORY / "scanned-page.pdf")
    rejected = PdfParser(
        ocr=FakeOcr(
            [[
                _ocr_box(
                    "Rejected",
                    (48.0, 48.0, 200.0, 76.0),
                    confidence=math.nextafter(threshold, 0.0),
                )
            ]]
        )
    ).parse(FIXTURE_DIRECTORY / "scanned-page.pdf")

    assert accepted.text == "Accepted"
    assert accepted.metadata.pdf is not None
    assert accepted.metadata.pdf.ocr_requirement is None
    assert rejected.text == ""
    assert rejected.metadata.pdf is not None
    assert rejected.metadata.pdf.ocr_requirement is not None


@pytest.mark.parametrize(
    ("ocr_text", "native_text", "deduplicated"),
    [
        ("Total", "Total", True),
        (" total ", "TOTAL", True),
        ("总 计", "总计", True),
        ("总计：", "总计：", True),
        ("Total", "Total amount", False),
        ("总计", "总计：", False),
    ],
)
def test_native_dedupe_requires_exact_normalized_text_identity(
    ocr_text: str,
    native_text: str,
    deduplicated: bool,
) -> None:
    box = _layout_box(ocr_text, (10.0, 10.0, 80.0, 24.0))
    span = _native_span(native_text, (10.0, 10.0, 80.0, 24.0))

    result = pdf_parser_module._deduplicate_ocr_boxes(
        (box,),
        spans=(span,),
        tables=(),
        limits=PdfResourceLimits(),
    )

    assert (result == ()) is deduplicated


def test_native_dedupe_requires_strong_geometry_for_repeated_text() -> None:
    box = _layout_box("Repeat", (10.0, 10.0, 80.0, 24.0))
    distant = _native_span("Repeat", (10.0, 60.0, 80.0, 74.0))
    sliver = _native_span("Repeat", (79.0, 10.0, 120.0, 24.0))

    result = pdf_parser_module._deduplicate_ocr_boxes(
        (box,),
        spans=(distant, sliver),
        tables=(),
        limits=PdfResourceLimits(),
    )

    assert result == (box,)


def test_native_dedupe_indexes_by_text_before_spatial_candidate_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spans = tuple(
        _native_span(
            f"native-{index}",
            (0.0, 0.0, 100.0, 100.0),
            span_index=index,
        )
        for index in range(100)
    )
    box = _layout_box("target", (10.0, 10.0, 20.0, 20.0))
    original = pdf_parser_module._ocr_box_duplicates_native
    inspections = 0

    def counted(*args: object, **kwargs: object) -> bool:
        nonlocal inspections
        inspections += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(pdf_parser_module, "_ocr_box_duplicates_native", counted)

    result = pdf_parser_module._deduplicate_ocr_boxes(
        (box,),
        spans=spans,
        tables=(),
        limits=PdfResourceLimits(),
    )

    assert result == (box,)
    assert inspections <= 1


def test_native_dedupe_candidate_budget_accepts_exact_boundary() -> None:
    box = _layout_box("same", (10.0, 10.0, 20.0, 20.0))
    spans = (
        _native_span("same", (19.5, 10.0, 30.0, 20.0), span_index=0),
        _native_span("same", (10.0, 10.0, 20.0, 20.0), span_index=1),
    )

    result = pdf_parser_module._deduplicate_ocr_boxes(
        (box,),
        spans=spans,
        tables=(),
        limits=PdfResourceLimits(max_ocr_dedupe_candidate_inspections_per_page=2),
    )

    assert result == ()


def test_native_dedupe_candidate_budget_rejects_one_over_boundary() -> None:
    box = _layout_box("same", (10.0, 10.0, 20.0, 20.0))
    spans = (
        _native_span("same", (19.5, 10.0, 30.0, 20.0), span_index=0),
        _native_span("same", (10.0, 10.0, 20.0, 20.0), span_index=1),
    )

    with pytest.raises(PdfResourceLimitError) as raised:
        pdf_parser_module._deduplicate_ocr_boxes(
            (box,),
            spans=spans,
            tables=(),
            limits=PdfResourceLimits(max_ocr_dedupe_candidate_inspections_per_page=1),
        )

    assert raised.value.limit == "max_ocr_dedupe_candidate_inspections_per_page"


@pytest.mark.parametrize("reverse", [False, True])
def test_duplicate_ocr_boxes_coalesce_to_highest_confidence_stably(reverse: bool) -> None:
    outputs = [
        _ocr_box("Repeat", (48.0, 48.0, 200.0, 76.0), confidence=0.7),
        _ocr_box("Repeat", (49.0, 48.0, 201.0, 76.0), confidence=0.95),
    ]
    if reverse:
        outputs.reverse()

    document = PdfParser(ocr=FakeOcr([outputs])).parse(
        FIXTURE_DIRECTORY / "scanned-page.pdf"
    )
    text_blocks = [block for block in document.blocks if block.text]

    assert [block.text for block in text_blocks] == ["Repeat"]
    assert text_blocks[0].source_locator["confidence"] == 0.95
    assert text_blocks[0].source_locator["boxes"][0]["confidence"] == 0.95


@pytest.mark.parametrize("reverse", [False, True])
def test_same_geometry_conflicting_ocr_text_selects_highest_confidence(
    reverse: bool,
) -> None:
    outputs = [
        _ocr_box("Wrong", (48.0, 48.0, 200.0, 76.0), confidence=0.6),
        _ocr_box("Right", (48.0, 48.0, 200.0, 76.0), confidence=0.9),
    ]
    if reverse:
        outputs.reverse()

    document = PdfParser(ocr=FakeOcr([outputs])).parse(
        FIXTURE_DIRECTORY / "scanned-page.pdf"
    )

    assert document.text == "Right"


@pytest.mark.parametrize("reverse", [False, True])
def test_same_geometry_conflicting_ocr_text_uses_stable_tie_order(
    reverse: bool,
) -> None:
    outputs = [
        _ocr_box("Zulu", (48.0, 48.0, 200.0, 76.0), confidence=0.9),
        _ocr_box("Alpha", (48.0, 48.0, 200.0, 76.0), confidence=0.9),
    ]
    if reverse:
        outputs.reverse()

    document = PdfParser(ocr=FakeOcr([outputs])).parse(
        FIXTURE_DIRECTORY / "scanned-page.pdf"
    )

    assert document.text == "Alpha"


def test_duplicate_candidate_budget_accepts_exact_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boxes = tuple(
        _layout_box(
            f"text-{index}",
            (10.0 + index / 10, 10.0, 30.0 + index / 10, 20.0),
            index=index,
        )
        for index in range(3)
    )
    inspections = 0

    def distinct(first: OcrLayoutBox, second: OcrLayoutBox) -> bool:
        nonlocal inspections
        del first, second
        inspections += 1
        return False

    monkeypatch.setattr(pdf_parser_module, "_ocr_boxes_are_near_identical", distinct)

    result = pdf_parser_module._coalesce_ocr_boxes(
        boxes,
        limits=PdfResourceLimits(max_ocr_duplicate_candidate_inspections_per_page=3),
    )

    assert result == boxes
    assert inspections == 3


def test_duplicate_candidate_budget_rejects_one_over_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boxes = tuple(
        _layout_box(
            f"text-{index}",
            (10.0 + index / 10, 10.0, 30.0 + index / 10, 20.0),
            index=index,
        )
        for index in range(3)
    )
    monkeypatch.setattr(
        pdf_parser_module,
        "_ocr_boxes_are_near_identical",
        lambda first, second: False,
    )

    with pytest.raises(PdfResourceLimitError) as raised:
        pdf_parser_module._coalesce_ocr_boxes(
            boxes,
            limits=PdfResourceLimits(max_ocr_duplicate_candidate_inspections_per_page=2),
        )

    assert raised.value.limit == "max_ocr_duplicate_candidate_inspections_per_page"
    assert raised.value.actual == 3


def test_duplicate_index_supports_500_same_coarse_bucket_nonduplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boxes = tuple(
        _layout_box(
            "same",
            (100.0, float(index * 3), 110.0, float(index * 3 + 1)),
            index=index,
        )
        for index in range(500)
    )
    original = pdf_parser_module._ocr_boxes_are_near_identical
    original_filter = pdf_parser_module._duplicate_features_may_match
    inspections = 0
    candidate_checks = 0

    def counted(first: OcrLayoutBox, second: OcrLayoutBox) -> bool:
        nonlocal inspections
        inspections += 1
        return original(first, second)

    def counted_filter(first: object, second: object) -> bool:
        nonlocal candidate_checks
        candidate_checks += 1
        return original_filter(first, second)

    monkeypatch.setattr(pdf_parser_module, "_ocr_boxes_are_near_identical", counted)
    monkeypatch.setattr(pdf_parser_module, "_duplicate_features_may_match", counted_filter)

    result = pdf_parser_module._coalesce_ocr_boxes(
        boxes,
        limits=PdfResourceLimits(),
    )

    assert len(result) == 500
    assert inspections < 500
    assert candidate_checks < 500


def test_exact_duplicate_preconsolidation_avoids_quadratic_range_traversal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boxes = tuple(
        _layout_box(
            "same",
            (10.0, 10.0, 30.0, 20.0),
            confidence=0.5 + index / 2_000,
            index=index,
        )
        for index in range(500)
    )
    original = pdf_parser_module._duplicate_xy_range
    traversed_entries = 0

    def counted_range(*args: object, **kwargs: object) -> tuple[int, ...]:
        nonlocal traversed_entries
        result = original(*args, **kwargs)
        traversed_entries += len(result)
        return result

    monkeypatch.setattr(pdf_parser_module, "_duplicate_xy_range", counted_range)

    result = pdf_parser_module._coalesce_ocr_boxes(
        boxes,
        limits=PdfResourceLimits(
            max_ocr_duplicate_candidate_inspections_per_page=500
        ),
    )

    assert len(result) == 1
    assert result[0].confidence == pytest.approx(0.7495)
    assert traversed_entries <= 500


def test_500_near_duplicates_stay_within_streaming_candidate_budget() -> None:
    boxes = tuple(
        _layout_box(
            "same",
            (10.0 + index / 1_000, 10.0, 30.0 + index / 1_000, 20.0),
            confidence=0.9,
            index=index,
        )
        for index in range(500)
    )

    result = pdf_parser_module._coalesce_ocr_boxes(
        boxes,
        limits=PdfResourceLimits(
            max_ocr_duplicate_candidate_inspections_per_page=500
        ),
    )

    assert len(result) == 1


def test_near_duplicate_streaming_budget_rejects_one_over_boundary() -> None:
    boxes = tuple(
        _layout_box(
            "same",
            (10.0 + index / 1_000, 10.0, 30.0 + index / 1_000, 20.0),
            confidence=0.9,
            index=index,
        )
        for index in range(500)
    )

    with pytest.raises(PdfResourceLimitError) as raised:
        pdf_parser_module._coalesce_ocr_boxes(
            boxes,
            limits=PdfResourceLimits(
                max_ocr_duplicate_candidate_inspections_per_page=498
            ),
        )

    assert raised.value.limit == "max_ocr_duplicate_candidate_inspections_per_page"
    assert raised.value.actual == 499


def test_duplicate_index_fails_closed_for_5000_adversarial_boxes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boxes = tuple(
        _layout_box(
            f"conflict-{index}",
            (
                10.0 + index / 10_000,
                10.0,
                30.0 + index / 10_000,
                20.0,
            ),
            index=index,
        )
        for index in range(5_000)
    )
    original_filter = pdf_parser_module._duplicate_features_may_match
    candidate_checks = 0

    def counted_filter(first: object, second: object) -> bool:
        nonlocal candidate_checks
        candidate_checks += 1
        return original_filter(first, second)

    monkeypatch.setattr(
        pdf_parser_module,
        "_ocr_boxes_are_near_identical",
        lambda first, second: False,
    )
    monkeypatch.setattr(pdf_parser_module, "_duplicate_features_may_match", counted_filter)

    with pytest.raises(PdfResourceLimitError) as raised:
        pdf_parser_module._coalesce_ocr_boxes(
            boxes,
            limits=PdfResourceLimits(
                max_ocr_duplicate_candidate_inspections_per_page=1_000
            ),
        )

    assert raised.value.limit == "max_ocr_duplicate_candidate_inspections_per_page"
    assert raised.value.actual == 1_001
    assert candidate_checks == 1_000


def test_duplicate_index_finds_near_duplicate_across_range_boundary() -> None:
    lower = _layout_box(
        "same",
        (9.95, 10.0, 29.95, 20.0),
        confidence=0.7,
        index=0,
    )
    upper = _layout_box(
        "same",
        (10.05, 10.0, 30.05, 20.0),
        confidence=0.9,
        index=1,
    )

    result = pdf_parser_module._coalesce_ocr_boxes(
        (lower, upper),
        limits=PdfResourceLimits(),
    )

    assert len(result) == 1
    assert result[0].confidence == 0.9


def test_duplicate_shift_chain_does_not_transitively_overmerge() -> None:
    boxes = tuple(
        _layout_box(
            "chain",
            (index * 2.5, 10.0, 100.0 + index * 2.5, 30.0),
            confidence=0.9,
            index=index,
        )
        for index in range(20)
    )
    assert all(
        pdf_parser_module._ocr_boxes_are_near_identical(first, second)
        for first, second in zip(boxes, boxes[1:], strict=False)
    )
    assert not pdf_parser_module._ocr_boxes_are_near_identical(boxes[0], boxes[-1])
    orders = (
        boxes,
        tuple(reversed(boxes)),
        boxes[::2] + boxes[1::2],
    )

    results = [
        pdf_parser_module._coalesce_ocr_boxes(
            order,
            limits=PdfResourceLimits(),
        )
        for order in orders
    ]

    assert len(results[0]) == 10
    assert results[1:] == [results[0], results[0]]
    assert [box.bbox[0] for box in results[0]] == [
        float(index * 5)
        for index in range(10)
    ]
def test_ocr_provider_capability_error_propagates_unchanged() -> None:
    class UnavailableOcr:
        def recognize(self, image: object, language: str) -> list[OcrTextBox]:
            del image, language
            raise OcrUnavailableError()

    with pytest.raises(OcrUnavailableError) as raised:
        PdfParser(ocr=UnavailableOcr()).parse(FIXTURE_DIRECTORY / "scanned-page.pdf")

    assert raised.value.code == "ocr_unavailable"
    assert raised.value.stage == "ocr"


def test_malformed_fake_ocr_boxes_are_output_errors_not_unavailable() -> None:
    class MalformedOcr:
        def recognize(self, image: object, language: str) -> list[OcrTextBox]:
            del image, language
            return [{"text": "invalid"}]  # type: ignore[list-item]

    with pytest.raises(OcrOutputError):
        PdfParser(ocr=MalformedOcr()).parse(FIXTURE_DIRECTORY / "scanned-page.pdf")


@pytest.mark.parametrize(
    ("limit_overrides", "expected_limit"),
    [
        ({"max_ocr_raster_width": 1}, "max_ocr_raster_width"),
        ({"max_ocr_raster_height": 1}, "max_ocr_raster_height"),
        ({"max_ocr_raster_pixels": 1}, "max_ocr_raster_pixels"),
        ({"max_ocr_raster_bytes": 1}, "max_ocr_raster_bytes"),
    ],
)
def test_raster_limits_reject_before_rendering_or_calling_ocr(
    monkeypatch: pytest.MonkeyPatch,
    limit_overrides: dict[str, int],
    expected_limit: str,
) -> None:
    def unexpected_render(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("raster allocation must not start after a known limit failure")

    monkeypatch.setattr(pymupdf.Page, "get_pixmap", unexpected_render)
    ocr = FakeOcr([[]])
    limits = PdfResourceLimits(**limit_overrides)

    with pytest.raises(PdfResourceLimitError) as raised:
        PdfParser(ocr=ocr, limits=limits).parse(FIXTURE_DIRECTORY / "scanned-page.pdf")

    assert raised.value.limit == expected_limit
    assert ocr.calls == []


@pytest.mark.parametrize(
    ("limit_overrides", "output", "expected_limit"),
    [
        (
            {"max_ocr_boxes_per_page": 1},
            [_ocr_box("first", (1.0, 1.0, 20.0, 10.0)), _ocr_box("second", (1, 20, 20, 30))],
            "max_ocr_boxes_per_page",
        ),
        (
            {"max_ocr_text_chars_per_page": 4},
            [_ocr_box("12345", (1.0, 1.0, 20.0, 10.0))],
            "max_ocr_text_chars_per_page",
        ),
    ],
)
def test_ocr_box_and_text_limits_are_typed(
    limit_overrides: dict[str, int],
    output: list[OcrTextBox],
    expected_limit: str,
) -> None:
    limits = PdfResourceLimits(**limit_overrides)
    with pytest.raises(PdfResourceLimitError) as raised:
        PdfParser(ocr=FakeOcr([output]), limits=limits).parse(
            FIXTURE_DIRECTORY / "scanned-page.pdf"
        )

    assert raised.value.limit == expected_limit


def test_ocr_render_dpi_is_named_and_bounded() -> None:
    from text_verification.parsers import pdf_parser

    assert pdf_parser.OCR_RENDER_DPI == 144
    assert 72 <= pdf_parser.OCR_RENDER_DPI <= 300


def test_ocr_pixmap_resource_is_closed_promptly() -> None:
    class ClosingPixmap:
        width = 20
        height = 20
        stride = 60

        def __init__(self) -> None:
            self.closed = False

        def tobytes(self, output: str) -> bytes:
            assert output == "png"
            return b"png"

        def close(self) -> None:
            self.closed = True

    pixmap = ClosingPixmap()
    page = SimpleNamespace(
        rect=SimpleNamespace(width=10.0, height=10.0),
        get_pixmap=lambda **kwargs: pixmap,
    )

    payload, width, height = pdf_parser_module._render_page_for_ocr(
        page,
        PdfResourceLimits(),
    )

    assert (payload, width, height) == (b"png", 20, 20)
    assert pixmap.closed is True


def test_successful_ocr_clears_pipeline_requirement_and_degradation() -> None:
    ocr = FakeOcr([[_ocr_box("Scanned text", (48.0, 48.0, 240.0, 76.0))]])
    pipeline = VerificationPipeline(
        parsers=ParserRegistry([PdfParser(ocr=ocr)]),
        checkers=CheckerRegistry([CompatibilityChecker()]),
        reviewer=None,
    )
    command = VerificationCommand(
        document_id=uuid4(),
        source_path=FIXTURE_DIRECTORY / "scanned-page.pdf",
        direct_text=None,
        source_name="scanned-page.pdf",
        file_type=FileType.PDF,
        options=VerificationOptions(enable_security=False, enable_sensitive=False),
        execution_mode=VerificationExecutionMode.SYNCHRONOUS,
    )

    result = pipeline.run(command)

    assert result.text == "Scanned text"
    assert result.ocr_requirement is None
    assert result.degradation.is_degraded is False
    assert result.degradation.reasons == ()
