from __future__ import annotations

import importlib
import math

import pytest
from pydantic import ValidationError

from text_verification.document_processing.errors import OcrLayoutError


def _layout_module():
    try:
        return importlib.import_module("text_verification.document_processing.layout")
    except ModuleNotFoundError:
        pytest.fail("OCR layout module is missing")


def _box(
    *,
    index: int,
    text: str,
    bbox: tuple[float, float, float, float],
    confidence: float = 0.9,
):
    layout = _layout_module()
    x0, y0, x1, y1 = bbox
    return layout.OcrLayoutBox(
        page=1,
        box_index=index,
        text=text,
        confidence=confidence,
        quad=((x0, y0), (x1, y0), (x1, y1), (x0, y1)),
    )


def _two_column_boxes(
    rows: tuple[tuple[str, str], ...],
    *,
    left_widths: tuple[float, ...] | None = None,
    right_widths: tuple[float, ...] | None = None,
) -> tuple[object, ...]:
    resolved_left_widths = left_widths or tuple(20.0 for _ in rows)
    resolved_right_widths = right_widths or tuple(60.0 for _ in rows)
    return tuple(
        box
        for row_index, (left, right) in enumerate(rows)
        for box in (
            _box(
                index=row_index * 2,
                text=left,
                bbox=(
                    10.0,
                    10.0 + row_index * 25.0,
                    10.0 + resolved_left_widths[row_index],
                    22.0 + row_index * 25.0,
                ),
            ),
            _box(
                index=row_index * 2 + 1,
                text=right,
                bbox=(
                    100.0,
                    10.0 + row_index * 25.0,
                    100.0 + resolved_right_widths[row_index],
                    22.0 + row_index * 25.0,
                ),
            ),
        )
    )


def test_layout_groups_heading_and_paragraph_lines_by_relative_height() -> None:
    layout = _layout_module()
    result = layout.build_ocr_layout(
        (
            _box(index=0, text="Document title", bbox=(10.0, 10.0, 150.0, 34.0)),
            _box(index=1, text="First body line", bbox=(10.0, 55.0, 130.0, 67.0)),
            _box(index=2, text="Second body line", bbox=(10.0, 70.0, 140.0, 82.0)),
        ),
        language="en",
    )

    assert [(element.kind, element.text) for element in result.elements] == [
        ("heading", "Document title"),
        ("paragraph", "First body line\nSecond body line"),
    ]
    assert [element.paragraph_index for element in result.elements] == [0, 1]


def test_layout_keeps_secondary_heading_separate_from_body() -> None:
    layout = _layout_module()
    result = layout.build_ocr_layout(
        (
            _box(index=0, text="Title", bbox=(10.0, 10.0, 150.0, 34.0)),
            _box(index=1, text="Subhead", bbox=(10.0, 45.0, 130.0, 65.0)),
            _box(index=2, text="Body", bbox=(10.0, 68.0, 100.0, 80.0)),
        ),
        language="en",
    )

    assert [(element.kind, element.text) for element in result.elements] == [
        ("heading", "Title"),
        ("heading", "Subhead"),
        ("paragraph", "Body"),
    ]


def test_layout_treats_all_large_and_single_line_pages_as_body_text() -> None:
    layout = _layout_module()
    all_large = layout.build_ocr_layout(
        (
            _box(index=0, text="Line one", bbox=(10.0, 10.0, 130.0, 34.0)),
            _box(index=1, text="Line two", bbox=(10.0, 38.0, 130.0, 62.0)),
        ),
        language="en",
    )
    single = layout.build_ocr_layout(
        (_box(index=0, text="Only line", bbox=(10.0, 10.0, 130.0, 34.0)),),
        language="en",
    )

    assert [(element.kind, element.text) for element in all_large.elements] == [
        ("paragraph", "Line one\nLine two")
    ]
    assert [(element.kind, element.text) for element in single.elements] == [
        ("paragraph", "Only line")
    ]


def test_layout_classifies_cjk_heading_and_body_deterministically() -> None:
    layout = _layout_module()
    boxes = (
        _box(index=0, text="标题", bbox=(10.0, 10.0, 80.0, 34.0)),
        _box(index=1, text="正文第一行", bbox=(10.0, 50.0, 100.0, 62.0)),
        _box(index=2, text="正文第二行", bbox=(10.0, 65.0, 100.0, 77.0)),
    )

    first = layout.build_ocr_layout(boxes, language="zh")
    second = layout.build_ocr_layout(tuple(reversed(boxes)), language="zh")

    assert [(element.kind, element.text) for element in first.elements] == [
        ("heading", "标题"),
        ("paragraph", "正文第一行\n正文第二行"),
    ]
    assert second == first


def test_layout_splits_materially_different_nonheading_line_heights() -> None:
    layout = _layout_module()
    result = layout.build_ocr_layout(
        (
            _box(index=0, text="Emphasized", bbox=(10.0, 10.0, 120.0, 26.0)),
            _box(index=1, text="Body", bbox=(10.0, 29.0, 100.0, 41.0)),
        ),
        language="en",
    )

    assert [(element.kind, element.text) for element in result.elements] == [
        ("paragraph", "Emphasized"),
        ("paragraph", "Body"),
    ]


def test_layout_uses_two_body_lines_over_single_small_footnote() -> None:
    layout = _layout_module()
    result = layout.build_ocr_layout(
        (
            _box(index=0, text="Footnote", bbox=(10.0, 10.0, 60.0, 16.0)),
            _box(index=1, text="Body one", bbox=(10.0, 30.0, 100.0, 42.0)),
            _box(index=2, text="Body two", bbox=(10.0, 45.0, 100.0, 57.0)),
        ),
        language="en",
    )

    assert [(element.kind, element.text) for element in result.elements] == [
        ("paragraph", "Footnote"),
        ("paragraph", "Body one\nBody two"),
    ]


def test_layout_uses_dominant_body_cluster_over_multiple_footnotes() -> None:
    layout = _layout_module()
    result = layout.build_ocr_layout(
        (
            _box(index=0, text="Foot one", bbox=(10.0, 10.0, 60.0, 16.0)),
            _box(index=1, text="Foot two", bbox=(10.0, 19.0, 60.0, 25.0)),
            _box(index=2, text="Body one", bbox=(10.0, 40.0, 100.0, 52.0)),
            _box(index=3, text="Body two", bbox=(10.0, 55.0, 100.0, 67.0)),
            _box(index=4, text="Body three", bbox=(10.0, 70.0, 100.0, 82.0)),
        ),
        language="en",
    )

    assert all(element.kind == "paragraph" for element in result.elements)
    assert result.elements[-1].text == "Body one\nBody two\nBody three"


def test_layout_uses_box_coverage_to_break_equal_line_count_cluster_tie() -> None:
    layout = _layout_module()
    result = layout.build_ocr_layout(
        (
            _box(index=0, text="Foot one", bbox=(10.0, 10.0, 60.0, 16.0)),
            _box(index=1, text="Foot two", bbox=(10.0, 19.0, 60.0, 25.0)),
            _box(index=2, text="Body", bbox=(10.0, 40.0, 40.0, 52.0)),
            _box(index=3, text="one", bbox=(42.0, 40.0, 65.0, 52.0)),
            _box(index=4, text="Body", bbox=(10.0, 55.0, 40.0, 67.0)),
            _box(index=5, text="two", bbox=(42.0, 55.0, 65.0, 67.0)),
        ),
        language="en",
    )

    assert all(element.kind == "paragraph" for element in result.elements)
    assert result.elements[-1].text == "Body one\nBody two"


def test_layout_uses_smaller_height_only_for_exact_cluster_tie() -> None:
    layout = _layout_module()
    result = layout.build_ocr_layout(
        (
            _box(index=0, text="Small one", bbox=(10.0, 10.0, 60.0, 16.0)),
            _box(index=1, text="Small two", bbox=(10.0, 19.0, 60.0, 25.0)),
            _box(index=2, text="Large one", bbox=(10.0, 40.0, 100.0, 52.0)),
            _box(index=3, text="Large two", bbox=(10.0, 55.0, 100.0, 67.0)),
        ),
        language="en",
    )

    assert [element.kind for element in result.elements] == [
        "paragraph",
        "heading",
        "heading",
    ]


def test_layout_detects_stable_two_by_two_table_without_hallucinating_prose_lists() -> None:
    layout = _layout_module()
    table = layout.build_ocr_layout(
        (
            _box(index=0, text="A1", bbox=(10.0, 10.0, 30.0, 22.0)),
            _box(index=1, text="B1", bbox=(100.0, 10.0, 124.0, 22.0)),
            _box(index=2, text="A2", bbox=(10.0, 35.0, 30.0, 47.0)),
            _box(index=3, text="B2", bbox=(100.0, 35.0, 124.0, 47.0)),
        ),
        language="en",
    )
    prose = layout.build_ocr_layout(
        (
            _box(index=0, text="1.", bbox=(10.0, 10.0, 20.0, 22.0)),
            _box(index=1, text="First item", bbox=(29.0, 10.0, 100.0, 22.0)),
            _box(index=2, text="2.", bbox=(10.0, 35.0, 20.0, 47.0)),
            _box(index=3, text="Second item", bbox=(29.0, 35.0, 108.0, 47.0)),
        ),
        language="en",
    )

    assert len(table.tables) == 1
    assert table.tables[0].row_count == 2
    assert table.tables[0].column_count == 2
    assert [
        (element.text, element.table_index, element.row_index, element.cell_index)
        for element in table.elements
    ] == [
        ("A1", 0, 0, 0),
        ("B1", 0, 0, 1),
        ("A2", 0, 1, 0),
        ("B2", 0, 1, 1),
    ]
    assert prose.tables == ()
    assert all(element.kind == "paragraph" for element in prose.elements)


@pytest.mark.parametrize(
    "rows",
    [
        (
            ("1.", "First numbered item"),
            ("2.", "Second numbered item"),
        ),
        (
            ("•", "First bullet item"),
            ("•", "Second bullet item"),
        ),
    ],
)
def test_layout_rejects_wide_gap_marker_lists_as_tables(
    rows: tuple[tuple[str, str], tuple[str, str]],
) -> None:
    layout = _layout_module()
    boxes = tuple(
        box
        for row_index, (marker, text) in enumerate(rows)
        for box in (
            _box(
                index=row_index * 2,
                text=marker,
                bbox=(10.0, 10.0 + row_index * 25.0, 18.0, 22.0 + row_index * 25.0),
            ),
            _box(
                index=row_index * 2 + 1,
                text=text,
                bbox=(80.0, 10.0 + row_index * 25.0, 190.0, 22.0 + row_index * 25.0),
            ),
        )
    )

    result = layout.build_ocr_layout(boxes, language="en")

    assert result.tables == ()
    assert all(element.kind == "paragraph" for element in result.elements)


def test_layout_rejects_ragged_two_column_prose_as_table() -> None:
    layout = _layout_module()
    result = layout.build_ocr_layout(
        (
            _box(index=0, text="Label", bbox=(10.0, 10.0, 30.0, 22.0)),
            _box(index=1, text="A much wider phrase", bbox=(100.0, 10.0, 180.0, 22.0)),
            _box(index=2, text="Topic", bbox=(10.0, 35.0, 34.0, 47.0)),
            _box(index=3, text="Short phrase", bbox=(100.0, 35.0, 150.0, 47.0)),
        ),
        language="en",
    )

    assert result.tables == ()


def test_layout_preserves_valid_three_by_two_table() -> None:
    layout = _layout_module()
    result = layout.build_ocr_layout(
        tuple(
            box
            for row_index, (left, right) in enumerate(
                (("A1", "B1"), ("A2", "B2"), ("A3", "B3"))
            )
            for box in (
                _box(
                    index=row_index * 2,
                    text=left,
                    bbox=(10.0, 10.0 + row_index * 25.0, 30.0, 22.0 + row_index * 25.0),
                ),
                _box(
                    index=row_index * 2 + 1,
                    text=right,
                    bbox=(100.0, 10.0 + row_index * 25.0, 124.0, 22.0 + row_index * 25.0),
                ),
            )
        ),
        language="en",
    )

    assert len(result.tables) == 1
    assert result.tables[0].row_count == 3
    assert result.tables[0].column_count == 2
    assert [
        (element.row_index, element.cell_index, element.text)
        for element in result.elements
    ] == [
        (0, 0, "A1"),
        (0, 1, "B1"),
        (1, 0, "A2"),
        (1, 1, "B2"),
        (2, 0, "A3"),
        (2, 1, "B3"),
    ]


def test_layout_accepts_varied_width_three_by_two_table_with_stable_anchors() -> None:
    layout = _layout_module()
    result = layout.build_ocr_layout(
        _two_column_boxes(
            (("A1", "Brief"), ("Long code", "Medium"), ("Z", "Long value")),
            left_widths=(20.0, 30.0, 40.0),
            right_widths=(30.0, 60.0, 90.0),
        ),
        language="en",
    )

    assert len(result.tables) == 1
    assert result.tables[0].row_count == 3
    assert result.tables[0].column_count == 2


@pytest.mark.parametrize(
    "widths",
    [
        ((20.0, 20.0), (40.0, 40.0)),
        ((20.0, 35.0), (30.0, 60.0)),
    ],
)
def test_layout_accepts_equal_and_varied_width_two_by_two_tables(
    widths: tuple[tuple[float, float], tuple[float, float]],
) -> None:
    layout = _layout_module()
    result = layout.build_ocr_layout(
        _two_column_boxes(
            (("A1", "B1"), ("A2", "B2")),
            left_widths=widths[0],
            right_widths=widths[1],
        ),
        language="en",
    )

    assert len(result.tables) == 1
    assert result.tables[0].row_count == 2


def test_layout_rejects_aligned_two_column_prose() -> None:
    layout = _layout_module()
    result = layout.build_ocr_layout(
        _two_column_boxes(
            (
                ("Overview", "This is the first prose line"),
                ("Details", "This is another prose line"),
            ),
            left_widths=(48.0, 48.0),
            right_widths=(150.0, 150.0),
        ),
        language="en",
    )

    assert result.tables == ()


@pytest.mark.parametrize(
    "markers",
    [
        ("一、", "二、"),
        ("1、", "2、"),
        ("a.", "b."),
        ("A)", "B)"),
        ("(a)", "(b)"),
        ("１、", "２、"),
        ("—", "—"),
        ("–", "–"),
        ("‣", "‣"),
    ],
)
def test_layout_rejects_locale_and_unicode_marker_lists(
    markers: tuple[str, str],
) -> None:
    layout = _layout_module()
    result = layout.build_ocr_layout(
        _two_column_boxes(
            ((markers[0], "First list item"), (markers[1], "Second list item")),
            left_widths=(12.0, 12.0),
            right_widths=(100.0, 100.0),
        ),
        language="en",
    )

    assert result.tables == ()


def test_layout_keeps_non_list_code_column_as_table() -> None:
    layout = _layout_module()
    result = layout.build_ocr_layout(
        _two_column_boxes(
            (("A01", "First description"), ("B02", "Second description")),
            left_widths=(24.0, 24.0),
            right_widths=(110.0, 110.0),
        ),
        language="en",
    )

    assert len(result.tables) == 1


@pytest.mark.parametrize(
    ("updates", "match"),
    [
        ({"page": True}, "page"),
        ({"box_index": True}, "box_index"),
        ({"confidence": math.nan}, "confidence"),
        ({"confidence": 1.1}, "confidence"),
        ({"quad": ((0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (3.0, 0.0))}, "quad"),
    ],
)
def test_layout_box_rejects_invalid_scalars_and_geometry(
    updates: dict[str, object],
    match: str,
) -> None:
    layout = _layout_module()
    values: dict[str, object] = {
        "page": 1,
        "box_index": 0,
        "text": "valid",
        "confidence": 0.9,
        "quad": ((0.0, 0.0), (10.0, 0.0), (10.0, 5.0), (0.0, 5.0)),
    }
    values.update(updates)

    with pytest.raises(ValidationError, match=match):
        layout.OcrLayoutBox(**values)


@pytest.mark.parametrize(
    "field",
    ["page", "table_index", "row_index", "cell_index"],
)
def test_layout_table_cell_rejects_boolean_indices(field: str) -> None:
    layout = _layout_module()
    values: dict[str, object] = {
        "page": 1,
        "text": "",
        "bbox": (0.0, 0.0, 10.0, 10.0),
        "confidence": 0.0,
        "table_index": 0,
        "row_index": 0,
        "cell_index": 0,
        "boxes": (),
    }
    values[field] = True

    with pytest.raises(ValidationError, match=field):
        layout.OcrTableCell(**values)


def test_layout_candidate_work_is_explicitly_bounded() -> None:
    layout = _layout_module()
    boxes = tuple(
        _box(
            index=index,
            text=str(index),
            bbox=(float(index), 0.0, float(index + 1), 100.0),
        )
        for index in range(3)
    )

    with pytest.raises(OcrLayoutError, match="candidate limit"):
        layout.build_ocr_layout(boxes, language="en", max_candidate_checks=1)
