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
