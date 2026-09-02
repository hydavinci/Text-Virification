from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pymupdf
import pytest
from pydantic import ValidationError

from text_verification.document_processing.pdf_models import (
    PdfCharacterMappingState,
    PdfImage,
    PdfPageKind,
    PdfPageMetadata,
    PdfResourceLimits,
    PdfTable,
    PdfTableCell,
    PdfTextSpan,
    PdfWritingMode,
)
from text_verification.parsers import pdf_parser as pdf_parser_module
from text_verification.parsers.errors import ParserError, PdfResourceLimitError
from text_verification.parsers.pdf_parser import PdfParser

FIXTURE_DIRECTORY = Path(__file__).resolve().parents[1] / "fixtures" / "pdf"


def _styled_boundary_pdf(
    target: Path,
    *,
    left: str,
    right: str,
    gap: float,
) -> Path:
    document = pymupdf.open()
    page = document.new_page(width=240, height=100)
    x, y = 24.0, 40.0
    page.insert_text((x, y), left, fontsize=12, fontname="helv")
    left_width = pymupdf.get_text_length(left, fontname="helv", fontsize=12)
    page.insert_text(
        (x + left_width + gap, y),
        right,
        fontsize=12,
        fontname="cour",
    )
    document.save(target)
    document.close()
    return target


class _SyntheticRawDictPage:
    def __init__(self, rawdict: dict[str, object]) -> None:
        self.rawdict = rawdict
        self.calls: list[tuple[str, int]] = []

    def get_text(self, option: str, *, flags: int) -> dict[str, object]:
        self.calls.append((option, flags))
        return self.rawdict


def _synthetic_document(
    rawdict: dict[str, object],
) -> tuple[list[object], str, tuple[object, ...], _SyntheticRawDictPage]:
    page = _SyntheticRawDictPage(rawdict)
    geometry = pdf_parser_module._PageGeometry(
        page_bbox=(0.0, 0.0, 100.0, 100.0),
        rotation_matrix=pymupdf.Matrix(1, 1),
    )
    raw_spans = pdf_parser_module._extract_raw_spans(page, geometry)
    spans = tuple(pdf_parser_module._extract_spans(raw_spans, []))
    metadata = PdfPageMetadata(
        page=1,
        kind=PdfPageKind.TEXT,
        page_bbox=(0.0, 0.0, 100.0, 100.0),
        text_length=sum(len(span.text) for span in spans),
        text_density=0.0,
        image_coverage=0.0,
        ocr_required=False,
        spans=spans,
    )
    blocks, text = pdf_parser_module._canonical_blocks((metadata,))
    return blocks, text, spans, page


def _raw_span(
    *,
    bbox: tuple[float, float, float, float],
    characters: list[tuple[str, object | None]],
    font: str = "Helvetica",
) -> dict[str, object]:
    return {
        "bbox": bbox,
        "font": font,
        "size": 12.0,
        "flags": 0,
        "color": 0,
        "chars": [
            {"c": text, **({"bbox": character_bbox} if character_bbox is not None else {})}
            for text, character_bbox in characters
        ],
    }


def _rawdict_with_line(
    spans: list[dict[str, object]],
    *,
    direction: tuple[float, float],
    writing_mode: int,
) -> dict[str, object]:
    return {
        "blocks": [
            {
                "type": 0,
                "lines": [
                    {
                        "bbox": (0.0, 0.0, 100.0, 100.0),
                        "dir": direction,
                        "wmode": writing_mode,
                        "spans": spans,
                    }
                ],
            }
        ]
    }


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


def test_rawdict_extraction_uses_authoritative_flags_without_image_payloads() -> None:
    _, _, _, page = _synthetic_document({"blocks": []})

    assert page.calls == [
        (
            "rawdict",
            pymupdf.TEXTFLAGS_RAWDICT & ~pymupdf.TEXT_PRESERVE_IMAGES,
        )
    ]


def test_large_scan_is_excluded_from_rawdict_but_still_classified_and_extracted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "large-scan.pdf"
    document = pymupdf.open()
    page = document.new_page(width=800, height=800)
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 1024, 1024), False)
    pixmap.clear_with(220)
    page.insert_image(page.rect, stream=pixmap.tobytes("png"))
    document.save(source)
    document.close()

    original_get_text = pymupdf.Page.get_text
    rawdict_calls: list[tuple[int | None, dict[str, object]]] = []

    def recording_get_text(
        page: pymupdf.Page,
        *args: object,
        **kwargs: object,
    ) -> Any:
        result = original_get_text(page, *args, **kwargs)
        if args and args[0] == "rawdict":
            rawdict_calls.append((kwargs.get("flags"), result))
        return result

    monkeypatch.setattr(pymupdf.Page, "get_text", recording_get_text)

    parsed = PdfParser().parse(source)

    assert rawdict_calls
    assert rawdict_calls[0][0] == (
        pymupdf.TEXTFLAGS_RAWDICT & ~pymupdf.TEXT_PRESERVE_IMAGES
    )
    assert all(
        block.get("type") != 1 and "image" not in block
        for block in rawdict_calls[0][1]["blocks"]
    )
    assert parsed.metadata.pdf is not None
    assert parsed.metadata.pdf.pages[0].kind is PdfPageKind.SCANNED
    assert len(parsed.metadata.pdf.pages[0].images) == 1


def test_parser_preserves_rtl_span_order_and_directional_gap_semantics() -> None:
    spans = [
        _raw_span(
            bbox=(70.0, 10.0, 90.0, 20.0),
            characters=[
                ("א", (80.0, 10.0, 90.0, 20.0)),
                ("ב", (70.0, 10.0, 80.0, 20.0)),
            ],
        ),
        _raw_span(
            bbox=(40.0, 10.0, 60.0, 20.0),
            characters=[
                ("ג", (50.0, 10.0, 60.0, 20.0)),
                ("ד", (40.0, 10.0, 50.0, 20.0)),
            ],
            font="Courier",
        ),
    ]

    blocks, text, extracted_spans, _ = _synthetic_document(
        _rawdict_with_line(spans, direction=(-1.0, 0.0), writing_mode=0)
    )

    assert text == "אב גד"
    assert [span.text for span in extracted_spans] == ["אב ", "גד"]
    assert all(span.line_direction == (-1.0, 0.0) for span in extracted_spans)
    assert all(span.writing_mode.value == 0 for span in extracted_spans)
    assert [
        character["text"] for character in blocks[0].source_locator["characters"]
    ] == ["א", "ב", " ", "ג", "ד"]


def test_parser_preserves_vertical_line_order_and_directional_gap_semantics() -> None:
    spans = [
        _raw_span(
            bbox=(10.0, 10.0, 20.0, 20.0),
            characters=[("上", (10.0, 10.0, 20.0, 20.0))],
        ),
        _raw_span(
            bbox=(10.0, 30.0, 20.0, 40.0),
            characters=[("下", (10.0, 30.0, 20.0, 40.0))],
            font="Courier",
        ),
    ]

    blocks, text, extracted_spans, _ = _synthetic_document(
        _rawdict_with_line(spans, direction=(0.0, 1.0), writing_mode=1)
    )

    assert text == "上 下"
    assert [span.text for span in extracted_spans] == ["上 ", "下"]
    assert all(span.line_direction == (0.0, 1.0) for span in extracted_spans)
    assert all(span.writing_mode.value == 1 for span in extracted_spans)
    assert blocks[0].source_locator["characters"][1]["mapping_state"] == "synthetic_space"


@pytest.mark.parametrize(
    "direction",
    [
        (0.0, 0.0),
        (float("nan"), 0.0),
        (float("inf"), 0.0),
        (1.0,),
        ("1", 0.0),
    ],
    ids=["zero", "nan", "infinite", "wrong-length", "non-numeric"],
)
def test_parser_rejects_malformed_raw_line_direction(direction: object) -> None:
    rawdict = {
        "blocks": [
            {
                "type": 0,
                "lines": [
                    {
                        "bbox": (10.0, 10.0, 20.0, 20.0),
                        "dir": direction,
                        "wmode": 0,
                        "spans": [
                            _raw_span(
                                bbox=(10.0, 10.0, 20.0, 20.0),
                                characters=[("A", (10.0, 10.0, 20.0, 20.0))],
                            )
                        ],
                    }
                ],
            }
        ]
    }

    with pytest.raises((TypeError, ValueError), match="line.direction"):
        _synthetic_document(rawdict)


def test_parser_preserves_glyphless_and_multi_codepoint_raw_groups() -> None:
    spans = [
        _raw_span(
            bbox=(10.0, 10.0, 50.0, 20.0),
            characters=[
                ("A", (10.0, 10.0, 20.0, 20.0)),
                ("\u200d", (20.0, 10.0, 20.0, 20.0)),
                ("B", None),
                ("👩‍💻", (30.0, 10.0, 50.0, 20.0)),
            ],
        )
    ]

    blocks, text, extracted_spans, _ = _synthetic_document(
        _rawdict_with_line(spans, direction=(1.0, 0.0), writing_mode=0)
    )

    assert text == "A\u200dB👩‍💻"
    characters = extracted_spans[0].characters
    assert [
        (
            character.text,
            character.source_start,
            character.source_end,
            character.mapping_state.value,
            character.bbox,
        )
        for character in characters
    ] == [
        ("A", 0, 1, "glyph", (10.0, 10.0, 20.0, 20.0)),
        ("\u200d", 1, 2, "glyphless", None),
        ("B", 2, 3, "glyphless", None),
        ("👩‍💻", 3, 6, "glyph", (30.0, 10.0, 50.0, 20.0)),
    ]
    source_groups = blocks[0].source_locator["characters"]
    assert len(source_groups) == 4
    assert source_groups[-1]["source_end"] == 6
    assert source_groups[-1]["bbox"] == [30.0, 10.0, 50.0, 20.0]
    assert len({character["group_id"] for character in source_groups}) == 4


@pytest.mark.parametrize(
    ("left", "right", "gap", "expected", "expected_segments"),
    [
        (
            "Left ",
            "Right",
            0.0,
            "Left Right",
            [(0, 5, "Left "), (5, 10, "Right")],
        ),
        (
            "Left",
            " Right",
            0.0,
            "Left Right",
            [(0, 5, "Left "), (5, 10, "Right")],
        ),
        (
            "Left ",
            " Right",
            0.0,
            "Left Right",
            [(0, 5, "Left "), (5, 10, "Right")],
        ),
        (
            "Left",
            "Right",
            1.5,
            "Left Right",
            [(0, 5, "Left "), (5, 10, "Right")],
        ),
        (
            "Left",
            "Right",
            0.5,
            "LeftRight",
            [(0, 4, "Left"), (4, 9, "Right")],
        ),
        (
            "Left  \t  ",
            "Right",
            0.0,
            "Left Right",
            [(0, 5, "Left "), (5, 10, "Right")],
        ),
    ],
    ids=[
        "trailing-only",
        "leading-only",
        "both-boundaries",
        "measured-word-gap",
        "contiguous-glyphs",
        "tabs-and-multiple-whitespace",
    ],
)
def test_parser_normalizes_styled_span_boundaries_with_exact_source_offsets(
    tmp_path: Path,
    left: str,
    right: str,
    gap: float,
    expected: str,
    expected_segments: list[tuple[int, int, str]],
) -> None:
    source = _styled_boundary_pdf(
        tmp_path / "styled-boundary.pdf",
        left=left,
        right=right,
        gap=gap,
    )

    document = PdfParser().parse(source)

    assert document.text == expected
    locator = document.blocks[0].source_locator
    assert [
        (segment["start"], segment["end"], segment["text"])
        for segment in locator["segments"]
    ] == expected_segments
    assert [
        (
            character["source_start"],
            character["source_end"],
            character["text"],
            character["mapping_state"],
            character["bbox"] is None,
        )
        for character in locator["characters"]
    ] == [
        (
            index,
            index + 1,
            character,
            "synthetic_space" if character.isspace() else "glyph",
            character.isspace(),
        )
        for index, character in enumerate(expected)
    ]


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
    first_cell = table.rows[0][0]
    assert [
        (character.text, character.mapping_state.value, character.bbox is not None)
        for character in first_cell.characters
    ] == [
        ("A", "glyph", True),
        ("1", "glyph", True),
        ("\n", "synthetic_space", False),
        ("A", "glyph", True),
        ("2", "glyph", True),
    ]
    first_cell_block = next(
        block
        for block in document.blocks
        if block.block_id == "pdf-page-1-table-0-row-0-cell-0"
    )
    assert first_cell_block.source_locator["characters"][0]["bbox"] is not None


def test_table_alignment_marks_only_unalignable_cell_text_unmapped() -> None:
    with pymupdf.open(FIXTURE_DIRECTORY / "table-structure.pdf") as document:
        page = document[0]
        geometry = pdf_parser_module._PageGeometry(
            page_bbox=tuple(page.rect),
            rotation_matrix=page.rotation_matrix,
        )
        raw_spans = pdf_parser_module._extract_raw_spans(page, geometry)
        spans = pdf_parser_module._extract_spans(raw_spans, [])

    characters = pdf_parser_module._align_cell_characters(
        "A1X",
        (40.0, 50.0, 95.0, 80.0),
        spans,
    )

    assert [
        (character.text, character.mapping_state.value)
        for character in characters
    ] == [
        ("A", "glyph"),
        ("1", "glyph"),
        ("X", "unmapped"),
    ]


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


@pytest.mark.parametrize(
    ("direction", "writing_mode", "first_text", "second_text"),
    [
        ((-1.0, 0.0), 0, "א", "ב"),
        ((0.0, 1.0), 1, "上", "下"),
    ],
    ids=["rtl-columns", "vertical-columns"],
)
def test_canonical_blocks_preserve_directional_raw_flow_with_table_and_image(
    direction: tuple[float, float],
    writing_mode: int,
    first_text: str,
    second_text: str,
) -> None:
    rawdict = {
        "blocks": [
            {
                "type": 0,
                "lines": [
                    {
                        "bbox": (70.0, 10.0, 90.0, 30.0),
                        "dir": direction,
                        "wmode": writing_mode,
                        "spans": [
                            _raw_span(
                                bbox=(70.0, 10.0, 90.0, 30.0),
                                characters=[(first_text, (70.0, 10.0, 90.0, 30.0))],
                            )
                        ],
                    },
                    {
                        "bbox": (10.0, 10.0, 30.0, 30.0),
                        "dir": direction,
                        "wmode": writing_mode,
                        "spans": [
                            _raw_span(
                                bbox=(10.0, 10.0, 30.0, 30.0),
                                characters=[(second_text, (10.0, 10.0, 30.0, 30.0))],
                            )
                        ],
                    },
                ],
            }
        ]
    }
    page = _SyntheticRawDictPage(rawdict)
    geometry = pdf_parser_module._PageGeometry(
        page_bbox=(0.0, 0.0, 100.0, 100.0),
        rotation_matrix=pymupdf.Matrix(1, 1),
    )
    spans = tuple(
        pdf_parser_module._extract_spans(
            pdf_parser_module._extract_raw_spans(page, geometry),
            [],
        )
    )
    table_cell = PdfTableCell(
        text="Cell",
        bbox=(35.0, 40.0, 55.0, 55.0),
        table_index=0,
        row_index=0,
        cell_index=0,
    )
    metadata = PdfPageMetadata(
        page=1,
        kind=PdfPageKind.TEXT,
        page_bbox=(0.0, 0.0, 100.0, 100.0),
        text_length=2,
        text_density=0.0,
        image_coverage=0.0,
        ocr_required=False,
        spans=spans,
        tables=(
            PdfTable(
                table_index=0,
                bbox=(35.0, 40.0, 55.0, 55.0),
                row_count=1,
                column_count=1,
                rows=((table_cell,),),
            ),
        ),
        images=(PdfImage(image_index=0, xref=1, bbox=(70.0, 70.0, 80.0, 80.0)),),
    )

    blocks, text = pdf_parser_module._canonical_blocks((metadata,))

    assert [block.text for block in blocks if block.kind == "paragraph"] == [
        first_text,
        second_text,
    ]
    assert [block.kind for block in blocks] == [
        "paragraph",
        "paragraph",
        "table_cell",
        "image",
    ]
    assert text == f"{first_text}\n{second_text}\nCell"


def test_canonical_blocks_merge_horizontal_heading_before_later_rtl_text() -> None:
    rawdict = {
        "blocks": [
            {
                "type": 0,
                "lines": [
                    {
                        "bbox": (10.0, 5.0, 30.0, 15.0),
                        "dir": (1.0, 0.0),
                        "wmode": 0,
                        "spans": [
                            _raw_span(
                                bbox=(10.0, 5.0, 30.0, 15.0),
                                characters=[("H", (10.0, 5.0, 30.0, 15.0))],
                            )
                        ],
                    },
                    {
                        "bbox": (70.0, 20.0, 90.0, 30.0),
                        "dir": (-1.0, 0.0),
                        "wmode": 0,
                        "spans": [
                            _raw_span(
                                bbox=(70.0, 20.0, 90.0, 30.0),
                                characters=[("R", (70.0, 20.0, 90.0, 30.0))],
                            )
                        ],
                    },
                ],
            }
        ]
    }
    page = _SyntheticRawDictPage(rawdict)
    geometry = pdf_parser_module._PageGeometry(
        page_bbox=(0.0, 0.0, 100.0, 100.0),
        rotation_matrix=pymupdf.Matrix(1, 1),
    )
    spans = tuple(
        pdf_parser_module._extract_spans(
            pdf_parser_module._extract_raw_spans(page, geometry),
            [],
        )
    )
    table_cell = PdfTableCell(
        text="Cell",
        bbox=(35.0, 40.0, 55.0, 55.0),
        table_index=0,
        row_index=0,
        cell_index=0,
    )
    metadata = PdfPageMetadata(
        page=1,
        kind=PdfPageKind.TEXT,
        page_bbox=(0.0, 0.0, 100.0, 100.0),
        text_length=2,
        text_density=0.0,
        image_coverage=0.0,
        ocr_required=False,
        spans=spans,
        tables=(
            PdfTable(
                table_index=0,
                bbox=(35.0, 40.0, 55.0, 55.0),
                row_count=1,
                column_count=1,
                rows=((table_cell,),),
            ),
        ),
        images=(PdfImage(image_index=0, xref=1, bbox=(70.0, 70.0, 80.0, 80.0)),),
    )

    blocks, text = pdf_parser_module._canonical_blocks((metadata,))

    assert [block.kind for block in blocks] == [
        "paragraph",
        "paragraph",
        "table_cell",
        "image",
    ]
    assert [block.text for block in blocks if block.kind == "paragraph"] == ["H", "R"]
    assert text == "H\nR\nCell"


def test_horizontal_only_lines_keep_visual_order() -> None:
    rawdict = {
        "blocks": [
            {
                "type": 0,
                "lines": [
                    {
                        "bbox": (10.0, 30.0, 20.0, 40.0),
                        "dir": (1.0, 0.0),
                        "wmode": 0,
                        "spans": [
                            _raw_span(
                                bbox=(10.0, 30.0, 20.0, 40.0),
                                characters=[("B", (10.0, 30.0, 20.0, 40.0))],
                            )
                        ],
                    },
                    {
                        "bbox": (10.0, 10.0, 20.0, 20.0),
                        "dir": (1.0, 0.0),
                        "wmode": 0,
                        "spans": [
                            _raw_span(
                                bbox=(10.0, 10.0, 20.0, 20.0),
                                characters=[("A", (10.0, 10.0, 20.0, 20.0))],
                            )
                        ],
                    },
                ],
            }
        ]
    }

    _, text, _, _ = _synthetic_document(rawdict)

    assert text == "A\nB"


def test_directional_runs_keep_local_raw_order_across_fixed_anchors() -> None:
    def item(
        text: str,
        bbox: tuple[float, float, float, float],
        line_index: int,
        *,
        block_id: str | None = None,
        ordinal: int | None = None,
        kind: str = "paragraph",
        directional: bool = True,
    ) -> SimpleNamespace:
        direction = (-1.0, 0.0) if directional else (1.0, 0.0)
        value = SimpleNamespace(
            text=text,
            bbox=bbox,
            line_index=line_index,
            line_direction=direction,
            writing_mode=PdfWritingMode.HORIZONTAL,
            block_id=block_id or text,
            ordinal=line_index if ordinal is None else ordinal,
            kind=kind,
            preserve_raw_flow=directional,
            source_start=0,
            mapping_state=PdfCharacterMappingState.GLYPH,
            group_id=f"group-{text}",
            raw_line_index=line_index,
            span_order=0,
            span_index=line_index,
            page_order=line_index,
            anchor_bbox=bbox,
        )
        value.character = value
        return value

    source_items = (
        item("D1A", (20.0, 50.0, 30.0, 60.0), 0, block_id="z-d1a", ordinal=0),
        item("D1B", (10.0, 50.0, 20.0, 60.0), 1, block_id="a-d1b", ordinal=0),
        item("H", (10.0, 30.0, 20.0, 40.0), 2, directional=False),
        item("D2A", (20.0, 10.0, 30.0, 20.0), 3),
        item("D2B", (10.0, 10.0, 20.0, 20.0), 4),
    )

    assert [line.text for line in pdf_parser_module._visual_lines(source_items)] == [
        "D2A",
        "D2B",
        "H",
        "D1A",
        "D1B",
    ]

    source_blocks = [
        source_items[0],
        source_items[1],
        source_items[2],
        item(
            "T",
            (10.0, 35.0, 20.0, 45.0),
            5,
            block_id="table",
            kind="table_cell",
            directional=False,
        ),
        item(
            "",
            (10.0, 40.0, 20.0, 50.0),
            6,
            block_id="image",
            kind="image",
            directional=False,
        ),
        source_items[3],
        source_items[4],
    ]

    assert [
        item.block_id for item in pdf_parser_module._order_page_blocks(source_blocks)
    ] == [
        "D2A",
        "D2B",
        "H",
        "table",
        "image",
        "z-d1a",
        "a-d1b",
    ]

    assert [
        group["text"]
        for group in pdf_parser_module._ordered_table_candidate_groups(
            source_items
        )
        if group["text"] != "\n"
    ] == ["D2A", "D2B", "H", "D1A", "D1B"]


@pytest.mark.parametrize(
    ("direction", "writing_mode"),
    [
        ((-1.0, 0.0), 0),
        ((0.0, 1.0), 1),
    ],
    ids=["rtl", "vertical"],
)
def test_table_alignment_inherits_matched_direction_and_raw_source_identity(
    direction: tuple[float, float],
    writing_mode: int,
) -> None:
    if writing_mode:
        first_bbox = (10.0, 10.0, 20.0, 20.0)
        second_bbox = (10.0, 20.0, 20.0, 30.0)
    else:
        first_bbox = (80.0, 10.0, 90.0, 20.0)
        second_bbox = (70.0, 10.0, 80.0, 20.0)
    rawdict = _rawdict_with_line(
        [
            _raw_span(bbox=first_bbox, characters=[("A", first_bbox)]),
            _raw_span(bbox=second_bbox, characters=[("B", second_bbox)]),
        ],
        direction=direction,
        writing_mode=writing_mode,
    )
    page = _SyntheticRawDictPage(rawdict)
    geometry = pdf_parser_module._PageGeometry(
        page_bbox=(0.0, 0.0, 100.0, 100.0),
        rotation_matrix=pymupdf.Matrix(1, 1),
    )
    spans = pdf_parser_module._extract_spans(
        pdf_parser_module._extract_raw_spans(page, geometry),
        [],
    )

    characters = pdf_parser_module._align_cell_characters(
        "AB",
        (0.0, 0.0, 100.0, 40.0),
        spans,
    )
    cell = PdfTableCell(
        text="AB",
        bbox=(0.0, 0.0, 100.0, 40.0),
        table_index=0,
        row_index=0,
        cell_index=0,
        characters=characters,
    )
    source_characters = pdf_parser_module._table_cell_source_characters(cell)

    assert [
        (
            character.line_direction,
            character.writing_mode.value,
            character.raw_line_index,
            character.span_order,
            character.group_id,
        )
        for character in characters
    ] == [
        (direction, writing_mode, 0, 0, "line-0-span-0-glyph-0"),
        (direction, writing_mode, 0, 1, "line-0-span-1-glyph-0"),
    ]
    assert [
        (
            value["line_direction"],
            value["writing_mode"],
            value["raw_line_index"],
            value["span_order"],
            value["group_id"],
        )
        for value in source_characters
    ] == [
        (list(direction), writing_mode, 0, 0, "line-0-span-0-glyph-0"),
        (list(direction), writing_mode, 0, 1, "line-0-span-1-glyph-0"),
    ]


def test_table_alignment_normalizes_whitespace_without_losing_source_groups() -> None:
    rawdict = {
        "blocks": [
            {
                "type": 0,
                "lines": [
                    {
                        "bbox": (10.0, 10.0, 20.0, 20.0),
                        "dir": (1.0, 0.0),
                        "wmode": 0,
                        "spans": [
                            _raw_span(
                                bbox=(10.0, 10.0, 20.0, 20.0),
                                characters=[("A", (10.0, 10.0, 20.0, 20.0))],
                            )
                        ],
                    },
                    {
                        "bbox": (10.0, 30.0, 20.0, 40.0),
                        "dir": (1.0, 0.0),
                        "wmode": 0,
                        "spans": [
                            _raw_span(
                                bbox=(10.0, 30.0, 20.0, 40.0),
                                characters=[("B", (10.0, 30.0, 20.0, 40.0))],
                            )
                        ],
                    },
                ],
            }
        ]
    }
    page = _SyntheticRawDictPage(rawdict)
    geometry = pdf_parser_module._PageGeometry(
        page_bbox=(0.0, 0.0, 100.0, 100.0),
        rotation_matrix=pymupdf.Matrix(1, 1),
    )
    spans = pdf_parser_module._extract_spans(
        pdf_parser_module._extract_raw_spans(page, geometry),
        [],
    )

    characters = pdf_parser_module._align_cell_characters(
        "A  B",
        (0.0, 0.0, 100.0, 100.0),
        spans,
    )

    assert [
        (character.text, character.mapping_state.value, character.group_id)
        for character in characters
    ] == [
        ("A", "glyph", "line-0-span-0-glyph-0"),
        ("  ", "synthetic_space", "line-1-separator-before"),
        ("B", "glyph", "line-1-span-0-glyph-0"),
    ]


def test_table_alignment_maps_later_exact_groups_after_unmatched_source_groups() -> None:
    rawdict = _rawdict_with_line(
        [
            _raw_span(
                bbox=(10.0, 10.0, 40.0, 20.0),
                characters=[
                    ("A", (10.0, 10.0, 20.0, 20.0)),
                    ("X", (20.0, 10.0, 30.0, 20.0)),
                    ("B", (30.0, 10.0, 40.0, 20.0)),
                ],
            )
        ],
        direction=(1.0, 0.0),
        writing_mode=0,
    )
    page = _SyntheticRawDictPage(rawdict)
    geometry = pdf_parser_module._PageGeometry(
        page_bbox=(0.0, 0.0, 100.0, 100.0),
        rotation_matrix=pymupdf.Matrix(1, 1),
    )
    spans = pdf_parser_module._extract_spans(
        pdf_parser_module._extract_raw_spans(page, geometry),
        [],
    )

    characters = pdf_parser_module._align_cell_characters(
        "AB",
        (0.0, 0.0, 100.0, 40.0),
        spans,
    )

    assert [
        (character.text, character.mapping_state.value, character.group_id)
        for character in characters
    ] == [
        ("A", "glyph", "line-0-span-0-glyph-0"),
        ("B", "glyph", "line-0-span-0-glyph-2"),
    ]


def test_table_alignment_prefers_later_complete_match_after_target_prefix() -> None:
    rawdict = _rawdict_with_line(
        [
            _raw_span(
                bbox=(10.0, 10.0, 30.0, 20.0),
                characters=[
                    ("A", (10.0, 10.0, 20.0, 20.0)),
                    ("B", (20.0, 10.0, 30.0, 20.0)),
                ],
            )
        ],
        direction=(1.0, 0.0),
        writing_mode=0,
    )
    page = _SyntheticRawDictPage(rawdict)
    geometry = pdf_parser_module._PageGeometry(
        page_bbox=(0.0, 0.0, 100.0, 100.0),
        rotation_matrix=pymupdf.Matrix(1, 1),
    )
    spans = pdf_parser_module._extract_spans(
        pdf_parser_module._extract_raw_spans(page, geometry),
        [],
    )

    characters = pdf_parser_module._align_cell_characters(
        "BAB",
        (0.0, 0.0, 100.0, 40.0),
        spans,
    )

    assert [
        (character.text, character.mapping_state.value, character.group_id)
        for character in characters
    ] == [
        ("B", "unmapped", "cell-unaligned-0"),
        ("A", "glyph", "line-0-span-0-glyph-0"),
        ("B", "glyph", "line-0-span-0-glyph-1"),
    ]


class _CountingSpanList(list[PdfTextSpan]):
    iterations: int = 0

    def __iter__(self) -> Iterator[PdfTextSpan]:
        self.iterations += 1
        return super().__iter__()


def _aligned_boundary_table() -> tuple[list[PdfTable], _CountingSpanList, set[str]]:
    rawdict = _rawdict_with_line(
        [
            _raw_span(
                bbox=(49.0, 10.0, 51.0, 20.0),
                characters=[("A", (49.0, 10.0, 51.0, 20.0))],
            )
        ],
        direction=(1.0, 0.0),
        writing_mode=0,
    )
    page = _SyntheticRawDictPage(rawdict)
    geometry = pdf_parser_module._PageGeometry(
        page_bbox=(0.0, 0.0, 100.0, 100.0),
        rotation_matrix=pymupdf.Matrix(1, 1),
    )
    spans = _CountingSpanList(
        pdf_parser_module._extract_spans(
            pdf_parser_module._extract_raw_spans(page, geometry),
            [],
        )
    )
    table = PdfTable(
        table_index=0,
        bbox=(0.0, 0.0, 100.0, 30.0),
        row_count=1,
        column_count=2,
        rows=(
            (
                PdfTableCell(
                    text="A",
                    bbox=(0.0, 0.0, 50.0, 30.0),
                    table_index=0,
                    row_index=0,
                    cell_index=0,
                ),
                PdfTableCell(
                    text="A",
                    bbox=(50.0, 0.0, 100.0, 30.0),
                    table_index=0,
                    row_index=0,
                    cell_index=1,
                ),
            ),
        ),
    )

    aligned, owned_group_ids = pdf_parser_module._align_table_characters(
        [table],
        spans,
        limits=PdfResourceLimits(),
    )
    return aligned, spans, owned_group_ids


def test_table_boundary_glyph_is_owned_by_exactly_one_cell() -> None:
    aligned, _, owned_group_ids = _aligned_boundary_table()

    cells = aligned[0].rows[0]
    assert owned_group_ids == {"line-0-span-0-glyph-0"}
    assert [
        (character.mapping_state.value, character.group_id)
        for character in cells[0].characters
    ] == [("glyph", "line-0-span-0-glyph-0")]
    assert [
        (character.mapping_state.value, character.group_id)
        for character in cells[1].characters
    ] == [("unmapped", "cell-unaligned-0")]
    assert sum(
        character.group_id == "line-0-span-0-glyph-0"
        for cell in cells
        for character in cell.characters
    ) == 1


def test_table_candidate_index_scans_page_spans_once() -> None:
    _, spans, _ = _aligned_boundary_table()

    assert spans.iterations == 1


def test_table_spatial_index_bounds_candidate_cell_inspections() -> None:
    cell_count = 256
    inspections = 0

    class _CountingCell:
        def __init__(self, index: int) -> None:
            self.key = (0, 0, index)
            self.order = index
            self._bbox = (float(index), 0.0, float(index + 1), 1.0)

        @property
        def bbox(self) -> tuple[float, float, float, float]:
            nonlocal inspections
            inspections += 1
            return self._bbox

    cells = tuple(_CountingCell(index) for index in range(cell_count))
    index = pdf_parser_module._TableCellSpatialIndex.build(cells)
    inspections = 0

    for cell_number, cell in enumerate(cells):
        x = float(cell_number)
        assert index.owner((x + 0.25, 0.25, x + 0.75, 0.75)) is cell

    assert inspections <= cell_count * 2


def test_table_spatial_index_resolves_nested_cells_by_specificity() -> None:
    outer = pdf_parser_module._TableCellCandidate(
        key=(0, 0, 0),
        bbox=(0.0, 0.0, 100.0, 100.0),
        order=0,
    )
    inner = pdf_parser_module._TableCellCandidate(
        key=(0, 0, 1),
        bbox=(10.0, 10.0, 20.0, 20.0),
        order=1,
    )
    index = pdf_parser_module._TableCellSpatialIndex.build((outer, inner))

    assert index.owner((50.0, 50.0, 51.0, 51.0)) is outer
    assert index.owner((12.0, 12.0, 13.0, 13.0)) is inner


@pytest.mark.parametrize(
    ("bboxes", "glyph", "owner_index"),
    [
        (
            ((0.0, 0.0, 20.0, 20.0), (0.0, 0.0, 20.0, 20.0)),
            (5.0, 5.0, 6.0, 6.0),
            0,
        ),
        (
            ((0.0, 0.0, 20.0, 20.0), (10.0, 0.0, 30.0, 20.0)),
            (12.0, 5.0, 25.0, 15.0),
            1,
        ),
    ],
    ids=["identical-stable-order", "partial-overlap-area"],
)
def test_table_spatial_index_resolves_adversarial_overlaps(
    bboxes: tuple[
        tuple[float, float, float, float],
        tuple[float, float, float, float],
    ],
    glyph: tuple[float, float, float, float],
    owner_index: int,
) -> None:
    cells = tuple(
        pdf_parser_module._TableCellCandidate(
            key=(0, 0, index),
            bbox=bbox,
            order=index,
        )
        for index, bbox in enumerate(bboxes)
    )

    assert pdf_parser_module._TableCellSpatialIndex.build(cells).owner(glyph) is cells[
        owner_index
    ]


def test_table_spatial_index_bounds_fully_overlapping_cell_inspections() -> None:
    cell_count = 256
    inspections = 0

    class _CountingCell:
        def __init__(self, index: int) -> None:
            self.key = (0, 0, index)
            self.order = index

        @property
        def bbox(self) -> tuple[float, float, float, float]:
            nonlocal inspections
            inspections += 1
            return (0.0, 0.0, 100.0, 100.0)

    cells = tuple(_CountingCell(index) for index in range(cell_count))
    index = pdf_parser_module._TableCellSpatialIndex.build(cells)
    inspections = 0

    for _ in range(cell_count):
        assert index.owner((50.0, 50.0, 51.0, 51.0)) is cells[0]

    assert inspections <= cell_count * 2


def test_partial_table_overlap_preserves_unowned_editable_glyph() -> None:
    rawdict = _rawdict_with_line(
        [
            _raw_span(
                bbox=(1.0, 1.0, 19.0, 9.0),
                characters=[
                    ("A", (1.0, 1.0, 9.0, 9.0)),
                    ("B", (11.0, 1.0, 19.0, 9.0)),
                ],
            )
        ],
        direction=(1.0, 0.0),
        writing_mode=0,
    )
    table = SimpleNamespace(
        bbox=(0.0, 0.0, 10.0, 10.0),
        rows=[SimpleNamespace(cells=[(0.0, 0.0, 10.0, 10.0)])],
        extract=lambda: [["A"]],
    )

    page = SimpleNamespace(
        rect=pymupdf.Rect(0.0, 0.0, 20.0, 20.0),
        rotation_matrix=pymupdf.Matrix(1, 1),
        get_text=lambda option, **_: rawdict if option == "rawdict" else "AB",
        get_images=lambda **_: [],
        find_tables=lambda: SimpleNamespace(tables=[table]),
    )

    extracted = pdf_parser_module._extract_page(
        page,
        1,
        PdfResourceLimits(),
    )
    blocks, text = pdf_parser_module._canonical_blocks((extracted.metadata,))

    assert text == "A\nB"
    assert [(block.kind, block.text) for block in blocks if block.text] == [
        ("table_cell", "A"),
        ("paragraph", "B"),
    ]
    outside_character = blocks[1].source_locator["characters"][0]
    assert (
        outside_character["text"],
        outside_character["mapping_state"],
        outside_character["bbox"],
        outside_character["source_start"],
        outside_character["source_end"],
        outside_character["span_index"],
        outside_character["group_id"],
    ) == (
        "B",
        "glyph",
        [11.0, 1.0, 19.0, 9.0],
        0,
        1,
        0,
        "line-0-span-0-glyph-1",
    )


def test_table_alignment_maps_complete_multi_codepoint_groups_only() -> None:
    rawdict = _rawdict_with_line(
        [
            _raw_span(
                bbox=(10.0, 10.0, 30.0, 20.0),
                characters=[("fi", (10.0, 10.0, 30.0, 20.0))],
            )
        ],
        direction=(1.0, 0.0),
        writing_mode=0,
    )
    page = _SyntheticRawDictPage(rawdict)
    geometry = pdf_parser_module._PageGeometry(
        page_bbox=(0.0, 0.0, 100.0, 100.0),
        rotation_matrix=pymupdf.Matrix(1, 1),
    )
    spans = pdf_parser_module._extract_spans(
        pdf_parser_module._extract_raw_spans(page, geometry),
        [],
    )

    complete = pdf_parser_module._align_cell_characters(
        "fi",
        (0.0, 0.0, 100.0, 40.0),
        spans,
    )
    partial = pdf_parser_module._align_cell_characters(
        "f",
        (0.0, 0.0, 100.0, 40.0),
        spans,
    )

    assert [
        (character.text, character.mapping_state.value, character.group_id)
        for character in complete
    ] == [("fi", "glyph", "line-0-span-0-glyph-0")]
    assert [
        (character.text, character.mapping_state.value, character.group_id)
        for character in partial
    ] == [("f", "unmapped", "cell-unaligned-0")]


def test_table_alignment_bounds_repetitive_glyph_comparisons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    glyph_count = 512
    rawdict = _rawdict_with_line(
        [
            _raw_span(
                bbox=(0.0, 0.0, float(glyph_count), 10.0),
                characters=[
                    ("A", (float(index), 0.0, float(index) + 0.5, 10.0))
                    for index in range(glyph_count)
                ],
            )
        ],
        direction=(1.0, 0.0),
        writing_mode=0,
    )
    page = _SyntheticRawDictPage(rawdict)
    geometry = pdf_parser_module._PageGeometry(
        page_bbox=(0.0, 0.0, float(glyph_count) + 1.0, 20.0),
        rotation_matrix=pymupdf.Matrix(1, 1),
    )
    spans = pdf_parser_module._extract_spans(
        pdf_parser_module._extract_raw_spans(page, geometry),
        [],
    )
    comparisons = 0
    original_match = pdf_parser_module._alignment_tokens_match

    def counting_match(source: str, target: str) -> bool:
        nonlocal comparisons
        comparisons += 1
        return original_match(source, target)

    monkeypatch.setattr(pdf_parser_module, "_alignment_tokens_match", counting_match)

    characters = pdf_parser_module._align_cell_characters(
        "A" * glyph_count,
        (0.0, 0.0, float(glyph_count) + 1.0, 20.0),
        spans,
    )

    assert len(characters) == glyph_count
    assert all(character.mapping_state.value == "glyph" for character in characters)
    assert comparisons <= glyph_count * 2


def test_table_alignment_enforces_candidate_limit_before_matching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rawdict = _rawdict_with_line(
        [
            _raw_span(
                bbox=(10.0, 10.0, 30.0, 20.0),
                characters=[
                    ("A", (10.0, 10.0, 20.0, 20.0)),
                    ("B", (20.0, 10.0, 30.0, 20.0)),
                ],
            )
        ],
        direction=(1.0, 0.0),
        writing_mode=0,
    )
    page = _SyntheticRawDictPage(rawdict)
    geometry = pdf_parser_module._PageGeometry(
        page_bbox=(0.0, 0.0, 100.0, 100.0),
        rotation_matrix=pymupdf.Matrix(1, 1),
    )
    spans = pdf_parser_module._extract_spans(
        pdf_parser_module._extract_raw_spans(page, geometry),
        [],
    )
    table = PdfTable(
        table_index=0,
        bbox=(0.0, 0.0, 100.0, 40.0),
        row_count=1,
        column_count=1,
        rows=(
            (
                PdfTableCell(
                    text="AB",
                    bbox=(0.0, 0.0, 100.0, 40.0),
                    table_index=0,
                    row_index=0,
                    cell_index=0,
                ),
            ),
        ),
    )

    aligned, _ = pdf_parser_module._align_table_characters(
        [table],
        spans,
        limits=PdfResourceLimits(max_table_glyph_candidates_per_cell=2),
    )

    assert [character.text for character in aligned[0].rows[0][0].characters] == ["A", "B"]

    def must_not_align(*args: object, **kwargs: object) -> tuple[object, ...]:
        del args, kwargs
        raise AssertionError("alignment must not run after a resource-limit violation")

    monkeypatch.setattr(pdf_parser_module, "_align_cell_characters", must_not_align)
    with pytest.raises(PdfResourceLimitError) as raised:
        pdf_parser_module._align_table_characters(
            [table],
            spans,
            limits=PdfResourceLimits(max_table_glyph_candidates_per_cell=1),
        )

    assert raised.value.limit == "max_table_glyph_candidates_per_cell"
    assert raised.value.maximum == 1
    assert raised.value.actual == 2


def test_parser_enforces_table_text_limits_at_exact_boundaries() -> None:
    source = FIXTURE_DIRECTORY / "table-structure.pdf"

    parsed = PdfParser(
        limits=PdfResourceLimits(
            max_table_text_chars_per_cell=5,
            max_table_text_chars_per_page=7,
        )
    ).parse(source)
    assert parsed.metadata.pdf is not None

    with pytest.raises(PdfResourceLimitError) as cell_raised:
        PdfParser(
            limits=PdfResourceLimits(
                max_table_text_chars_per_cell=4,
                max_table_text_chars_per_page=7,
            )
        ).parse(source)
    assert cell_raised.value.limit == "max_table_text_chars_per_cell"
    assert cell_raised.value.maximum == 4
    assert cell_raised.value.actual == 5

    with pytest.raises(PdfResourceLimitError) as page_raised:
        PdfParser(
            limits=PdfResourceLimits(
                max_table_text_chars_per_cell=5,
                max_table_text_chars_per_page=6,
            )
        ).parse(source)
    assert page_raised.value.limit == "max_table_text_chars_per_page"
    assert page_raised.value.maximum == 6
    assert page_raised.value.actual == 7
