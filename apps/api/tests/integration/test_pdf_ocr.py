from __future__ import annotations

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
from text_verification.document_processing.ocr_provider import OcrTextBox
from text_verification.document_processing.pdf_models import PdfPageKind, PdfResourceLimits
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
    ("fixture", "expected_page_bbox"),
    [
        ("rotated-cropped-scan-90.pdf", (0.0, 0.0, 140.0, 200.0)),
        ("rotated-cropped-scan-270.pdf", (0.0, 0.0, 140.0, 200.0)),
    ],
)
def test_rotated_cropped_ocr_coordinates_map_to_visual_pdf_space(
    fixture: str,
    expected_page_bbox: tuple[float, float, float, float],
) -> None:
    ocr = FakeOcr([[_ocr_box("Rotated", (28.0, 40.0, 84.0, 80.0))]])

    document = PdfParser(ocr=ocr).parse(FIXTURE_DIRECTORY / fixture)
    block = next(block for block in document.blocks if block.text == "Rotated")

    assert document.metadata.pdf is not None
    assert document.metadata.pdf.pages[0].page_bbox == expected_page_bbox
    assert block.bbox == pytest.approx((14.0, 20.0, 42.0, 40.0))
    assert block.source_locator["quad"] == [
        [14.0, 20.0],
        [42.0, 20.0],
        [42.0, 40.0],
        [14.0, 40.0],
    ]


def test_empty_ocr_keeps_typed_requirement_and_records_warning() -> None:
    document = PdfParser(ocr=FakeOcr([[]])).parse(FIXTURE_DIRECTORY / "scanned-page.pdf")

    assert document.metadata.pdf is not None
    assert document.metadata.pdf.ocr_requirement is not None
    assert document.metadata.pdf.ocr_requirement.mode == "required"
    assert document.metadata.pdf.ocr_requirement.pages == (1,)
    assert document.metadata.pdf.warnings[-1].stage == "ocr"
    assert document.metadata.pdf.warnings[-1].code == "pdf_ocr_no_text"


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
