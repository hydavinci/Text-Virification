from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from math import isfinite
from numbers import Real
from statistics import median
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from text_verification.document_processing.errors import OcrLayoutError

PositiveInt = Annotated[int, Field(strict=True, ge=1)]
NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
BBox = tuple[float, float, float, float]
Quad = tuple[
    tuple[float, float],
    tuple[float, float],
    tuple[float, float],
    tuple[float, float],
]
OcrElementKind = Literal["paragraph", "heading", "table_cell"]

DEFAULT_MAX_LAYOUT_BOXES = 5_000
DEFAULT_MAX_LAYOUT_CANDIDATE_CHECKS = 250_000
_LINE_OVERLAP_RATIO = 0.45
_BASELINE_RATIO = 0.45
_HEADING_HEIGHT_RATIO = 1.35
_BODY_CLUSTER_GAP_RATIO = 1.3
_PARAGRAPH_HEIGHT_RATIO = 1.25
_MIN_TABLE_GAP_HEIGHT_RATIO = 1.5
_MAX_TABLE_ROW_GAP_HEIGHT_RATIO = 4.0
_LIST_MARKER = re.compile(r"^(?:(\d+)[.)]|[•●▪◦*-])$")


class _LayoutModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class OcrLayoutBox(_LayoutModel):
    page: PositiveInt
    box_index: NonNegativeInt
    text: str
    confidence: float
    quad: Quad

    @field_validator("text", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> str:
        if not isinstance(value, str):
            raise TypeError("text must be a string")
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("text must not be empty")
        return normalized

    @field_validator("confidence", mode="before")
    @classmethod
    def validate_confidence(cls, value: object) -> float:
        confidence = _finite_float(value, field_name="confidence")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        return confidence

    @field_validator("quad", mode="before")
    @classmethod
    def validate_quad(cls, value: object) -> Quad:
        return _quad(value)

    @property
    def bbox(self) -> BBox:
        return _combined_bbox(
            (point[0], point[1], point[0], point[1])
            for point in self.quad
        )

    @property
    def height(self) -> float:
        return self.bbox[3] - self.bbox[1]

    @property
    def baseline(self) -> float:
        return max(point[1] for point in self.quad)


class OcrLayoutLine(_LayoutModel):
    page: PositiveInt
    line_index: NonNegativeInt
    text: str = Field(min_length=1)
    bbox: BBox
    confidence: float
    boxes: tuple[OcrLayoutBox, ...] = Field(min_length=1)

    @field_validator("bbox", mode="before")
    @classmethod
    def validate_bbox(cls, value: object) -> BBox:
        return _bbox(value, field_name="bbox")

    @field_validator("confidence", mode="before")
    @classmethod
    def validate_confidence(cls, value: object) -> float:
        confidence = _finite_float(value, field_name="confidence")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        return confidence

    @model_validator(mode="after")
    def validate_boxes(self) -> OcrLayoutLine:
        if any(box.page != self.page for box in self.boxes):
            raise ValueError("line boxes must belong to the same page")
        if len({box.box_index for box in self.boxes}) != len(self.boxes):
            raise ValueError("line box indices must be unique")
        if self.bbox != _combined_bbox(box.bbox for box in self.boxes):
            raise ValueError("line bbox must contain its boxes exactly")
        return self


class OcrTableCell(_LayoutModel):
    page: PositiveInt
    text: str
    bbox: BBox
    confidence: float
    table_index: NonNegativeInt
    row_index: NonNegativeInt
    cell_index: NonNegativeInt
    boxes: tuple[OcrLayoutBox, ...] = ()

    @field_validator("text", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> str:
        if not isinstance(value, str):
            raise TypeError("text must be a string")
        return " ".join(value.split())

    @field_validator("bbox", mode="before")
    @classmethod
    def validate_bbox(cls, value: object) -> BBox:
        return _bbox(value, field_name="bbox")

    @field_validator("confidence", mode="before")
    @classmethod
    def validate_confidence(cls, value: object) -> float:
        confidence = _finite_float(value, field_name="confidence")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        return confidence

    @model_validator(mode="after")
    def validate_boxes(self) -> OcrTableCell:
        if any(box.page != self.page for box in self.boxes):
            raise ValueError("cell boxes must belong to the same page")
        if not self.text and self.boxes:
            raise ValueError("empty structural cells must not contain OCR boxes")
        return self


class OcrTable(_LayoutModel):
    page: PositiveInt
    table_index: NonNegativeInt
    bbox: BBox
    confidence: float
    row_count: PositiveInt
    column_count: PositiveInt
    rows: tuple[tuple[OcrTableCell, ...], ...]

    @field_validator("bbox", mode="before")
    @classmethod
    def validate_bbox(cls, value: object) -> BBox:
        return _bbox(value, field_name="bbox")

    @field_validator("confidence", mode="before")
    @classmethod
    def validate_confidence(cls, value: object) -> float:
        confidence = _finite_float(value, field_name="confidence")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        return confidence

    @model_validator(mode="after")
    def validate_shape(self) -> OcrTable:
        if self.row_count < 2 or self.column_count < 2:
            raise ValueError("OCR tables require at least two rows and two columns")
        if len(self.rows) != self.row_count:
            raise ValueError("table row_count must match rows")
        if any(len(row) != self.column_count for row in self.rows):
            raise ValueError("table column_count must match every row")
        for row_index, row in enumerate(self.rows):
            for cell_index, cell in enumerate(row):
                if (
                    cell.page != self.page
                    or cell.table_index != self.table_index
                    or cell.row_index != row_index
                    or cell.cell_index != cell_index
                ):
                    raise ValueError("table cells must match their table coordinates")
        return self


class OcrLayoutElement(_LayoutModel):
    kind: OcrElementKind
    page: PositiveInt
    text: str = Field(min_length=1)
    bbox: BBox
    confidence: float
    language: str = Field(min_length=1)
    paragraph_index: NonNegativeInt | None = None
    table_index: NonNegativeInt | None = None
    row_index: NonNegativeInt | None = None
    cell_index: NonNegativeInt | None = None
    boxes: tuple[OcrLayoutBox, ...] = Field(min_length=1)

    @field_validator("bbox", mode="before")
    @classmethod
    def validate_bbox(cls, value: object) -> BBox:
        return _bbox(value, field_name="bbox")

    @field_validator("confidence", mode="before")
    @classmethod
    def validate_confidence(cls, value: object) -> float:
        confidence = _finite_float(value, field_name="confidence")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        return confidence

    @field_validator("language", mode="before")
    @classmethod
    def normalize_language(cls, value: object) -> str:
        if not isinstance(value, str):
            raise TypeError("language must be a string")
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("language must not be empty")
        return normalized

    @model_validator(mode="after")
    def validate_coordinates(self) -> OcrLayoutElement:
        table_coordinates = (self.table_index, self.row_index, self.cell_index)
        if self.kind == "table_cell":
            if any(value is None for value in table_coordinates):
                raise ValueError("table cells require table, row, and cell indices")
            if self.paragraph_index is not None:
                raise ValueError("table cells must not have a paragraph index")
        else:
            if self.paragraph_index is None:
                raise ValueError("paragraphs and headings require a paragraph index")
            if any(value is not None for value in table_coordinates):
                raise ValueError("paragraphs and headings must not have table coordinates")
        if any(box.page != self.page for box in self.boxes):
            raise ValueError("element boxes must belong to the same page")
        return self


class OcrLayoutResult(_LayoutModel):
    elements: tuple[OcrLayoutElement, ...] = ()
    tables: tuple[OcrTable, ...] = ()


@dataclass
class _LineBuilder:
    boxes: list[OcrLayoutBox]
    x0: float
    y0: float
    x1: float
    y1: float
    baseline_total: float

    @property
    def bbox(self) -> BBox:
        return self.x0, self.y0, self.x1, self.y1

    @property
    def baseline(self) -> float:
        return self.baseline_total / len(self.boxes)

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @classmethod
    def from_box(cls, box: OcrLayoutBox) -> _LineBuilder:
        x0, y0, x1, y1 = box.bbox
        return cls(
            boxes=[box],
            x0=x0,
            y0=y0,
            x1=x1,
            y1=y1,
            baseline_total=box.baseline,
        )

    def add(self, box: OcrLayoutBox) -> None:
        x0, y0, x1, y1 = box.bbox
        self.boxes.append(box)
        self.x0 = min(self.x0, x0)
        self.y0 = min(self.y0, y0)
        self.x1 = max(self.x1, x1)
        self.y1 = max(self.y1, y1)
        self.baseline_total += box.baseline


def build_ocr_layout(
    boxes: tuple[OcrLayoutBox, ...],
    *,
    language: str,
    max_boxes: int = DEFAULT_MAX_LAYOUT_BOXES,
    max_candidate_checks: int = DEFAULT_MAX_LAYOUT_CANDIDATE_CHECKS,
) -> OcrLayoutResult:
    _strict_limit(max_boxes, field_name="max_boxes")
    _strict_limit(max_candidate_checks, field_name="max_candidate_checks")
    if len(boxes) > max_boxes:
        raise OcrLayoutError(f"OCR layout box limit exceeded ({len(boxes)} > {max_boxes}).")
    if not boxes:
        return OcrLayoutResult()
    if len({box.page for box in boxes}) != 1:
        raise OcrLayoutError("OCR layout boxes must belong to exactly one page.")
    if len({box.box_index for box in boxes}) != len(boxes):
        raise OcrLayoutError("OCR layout box indices must be unique.")

    lines = _group_lines(boxes, language=language, max_candidate_checks=max_candidate_checks)
    tables, table_line_indices = _detect_tables(lines)
    elements = [
        _table_element(cell, language=language)
        for table in tables
        for row in table.rows
        for cell in row
        if cell.text
    ]
    elements.extend(
        _text_elements(
            tuple(line for line in lines if line.line_index not in table_line_indices),
            language=language,
        )
    )
    return OcrLayoutResult(
        elements=tuple(sorted(elements, key=_element_order)),
        tables=tuple(tables),
    )


def _group_lines(
    boxes: tuple[OcrLayoutBox, ...],
    *,
    language: str,
    max_candidate_checks: int,
) -> tuple[OcrLayoutLine, ...]:
    builders: list[_LineBuilder] = []
    active: list[_LineBuilder] = []
    checks = 0
    for box in sorted(boxes, key=_box_order):
        active = [
            line
            for line in active
            if line.bbox[3] + max(line.height, box.height) * _BASELINE_RATIO >= box.bbox[1]
        ]
        candidates: list[tuple[float, float, float, _LineBuilder]] = []
        for line in active:
            checks += 1
            if checks > max_candidate_checks:
                raise OcrLayoutError("OCR line grouping candidate limit exceeded.")
            overlap = _vertical_overlap_ratio(line.bbox, box.bbox)
            baseline_distance = abs(line.baseline - box.baseline)
            if (
                overlap >= _LINE_OVERLAP_RATIO
                or baseline_distance <= max(line.height, box.height) * _BASELINE_RATIO
            ):
                candidates.append(
                    (-overlap, baseline_distance, line.bbox[0], line)
                )
        if candidates:
            selected = min(candidates, key=lambda candidate: candidate[:3])[3]
            selected.add(box)
        else:
            selected = _LineBuilder.from_box(box)
            builders.append(selected)
            active.append(selected)

    ordered_builders = sorted(builders, key=lambda line: (line.bbox[1], line.bbox[0]))
    return tuple(
        _line(builder, line_index=index, language=language)
        for index, builder in enumerate(ordered_builders)
    )


def _line(builder: _LineBuilder, *, line_index: int, language: str) -> OcrLayoutLine:
    boxes = tuple(sorted(builder.boxes, key=lambda box: (box.bbox[0], box.box_index)))
    return OcrLayoutLine(
        page=boxes[0].page,
        line_index=line_index,
        text=_join_box_text(boxes, language=language),
        bbox=_combined_bbox(box.bbox for box in boxes),
        confidence=_mean_confidence(boxes),
        boxes=boxes,
    )


def _detect_tables(
    lines: tuple[OcrLayoutLine, ...],
) -> tuple[list[OcrTable], set[int]]:
    candidate_rows = [line for line in lines if _is_table_row_candidate(line)]
    groups: list[list[OcrLayoutLine]] = []
    current: list[OcrLayoutLine] = []
    for row in candidate_rows:
        if current and not _rows_align(current[-1], row):
            if len(current) >= 2:
                groups.append(current)
            current = []
        current.append(row)
    if len(current) >= 2:
        groups.append(current)

    tables: list[OcrTable] = []
    consumed: set[int] = set()
    for rows in groups:
        if not _rows_have_stable_columns(rows) or _is_marker_list(rows):
            continue
        table_index = len(tables)
        column_count = len(rows[0].boxes)
        cells = tuple(
            tuple(
                OcrTableCell(
                    page=row.page,
                    text=box.text,
                    bbox=box.bbox,
                    confidence=box.confidence,
                    table_index=table_index,
                    row_index=row_index,
                    cell_index=cell_index,
                    boxes=(box,),
                )
                for cell_index, box in enumerate(row.boxes)
            )
            for row_index, row in enumerate(rows)
        )
        all_cells = tuple(cell for row in cells for cell in row)
        tables.append(
            OcrTable(
                page=rows[0].page,
                table_index=table_index,
                bbox=_combined_bbox(cell.bbox for cell in all_cells),
                confidence=sum(cell.confidence for cell in all_cells) / len(all_cells),
                row_count=len(rows),
                column_count=column_count,
                rows=cells,
            )
        )
        consumed.update(row.line_index for row in rows)
    return tables, consumed


def _is_table_row_candidate(line: OcrLayoutLine) -> bool:
    if len(line.boxes) < 2:
        return False
    gaps = [
        right.bbox[0] - left.bbox[2]
        for left, right in zip(line.boxes, line.boxes[1:], strict=False)
    ]
    if any(gap <= 0.0 for gap in gaps):
        return False
    typical_height = median(box.height for box in line.boxes)
    minimum_gap = max(4.0, typical_height * _MIN_TABLE_GAP_HEIGHT_RATIO)
    if min(gaps) < minimum_gap:
        return False
    return max(gaps) - min(gaps) <= max(typical_height * 2.0, median(gaps) * 0.5)


def _rows_align(first: OcrLayoutLine, second: OcrLayoutLine) -> bool:
    if len(first.boxes) != len(second.boxes):
        return False
    typical_height = median(
        box.height for box in (*first.boxes, *second.boxes)
    )
    row_gap = second.bbox[1] - first.bbox[3]
    if row_gap < 0.0 or row_gap > typical_height * _MAX_TABLE_ROW_GAP_HEIGHT_RATIO:
        return False
    alignment_tolerance = max(4.0, typical_height * 0.75)
    if any(
        abs(first_box.bbox[0] - second_box.bbox[0]) > alignment_tolerance
        for first_box, second_box in zip(first.boxes, second.boxes, strict=True)
    ):
        return False
    first_gaps = [
        right.bbox[0] - left.bbox[2]
        for left, right in zip(first.boxes, first.boxes[1:], strict=False)
    ]
    second_gaps = [
        right.bbox[0] - left.bbox[2]
        for left, right in zip(second.boxes, second.boxes[1:], strict=False)
    ]
    return all(
        abs(first_gap - second_gap) <= max(typical_height, max(first_gap, second_gap) * 0.25)
        for first_gap, second_gap in zip(first_gaps, second_gaps, strict=True)
    )


def _rows_have_stable_columns(rows: list[OcrLayoutLine]) -> bool:
    typical_height = median(
        box.height
        for row in rows
        for box in row.boxes
    )
    for column_index in range(len(rows[0].boxes)):
        widths = [
            row.boxes[column_index].bbox[2] - row.boxes[column_index].bbox[0]
            for row in rows
        ]
        if max(widths) - min(widths) > max(
            typical_height * 0.75,
            median(widths) * 0.25,
        ):
            return False
    return True


def _is_marker_list(rows: list[OcrLayoutLine]) -> bool:
    markers = [_LIST_MARKER.fullmatch(row.boxes[0].text) for row in rows]
    if any(marker is None for marker in markers):
        return False
    first_widths = [
        row.boxes[0].bbox[2] - row.boxes[0].bbox[0]
        for row in rows
    ]
    prose_widths = [
        row.boxes[1].bbox[2] - row.boxes[1].bbox[0]
        for row in rows
    ]
    if max(first_widths) > median(prose_widths) * 0.35:
        return False
    number_values = [
        int(number)
        for marker in markers
        if marker is not None and (number := marker.group(1)) is not None
    ]
    return not number_values or number_values == list(
        range(number_values[0], number_values[0] + len(number_values))
    )


def _text_elements(
    lines: tuple[OcrLayoutLine, ...],
    *,
    language: str,
) -> list[OcrLayoutElement]:
    if not lines:
        return []
    body_height = _body_line_height(lines)
    elements: list[OcrLayoutElement] = []
    paragraph_lines: list[OcrLayoutLine] = []
    paragraph_index = 0

    def flush_paragraph() -> None:
        nonlocal paragraph_index
        if not paragraph_lines:
            return
        boxes = tuple(box for line in paragraph_lines for box in line.boxes)
        elements.append(
            OcrLayoutElement(
                kind="paragraph",
                page=paragraph_lines[0].page,
                text="\n".join(line.text for line in paragraph_lines),
                bbox=_combined_bbox(line.bbox for line in paragraph_lines),
                confidence=_mean_confidence(boxes),
                language=language,
                paragraph_index=paragraph_index,
                boxes=boxes,
            )
        )
        paragraph_index += 1
        paragraph_lines.clear()

    for line in lines:
        line_height = line.bbox[3] - line.bbox[1]
        is_heading = (
            line_height >= max(body_height * _HEADING_HEIGHT_RATIO, body_height + 2.0)
            and len(line.text) <= 160
        )
        if is_heading:
            flush_paragraph()
            elements.append(
                OcrLayoutElement(
                    kind="heading",
                    page=line.page,
                    text=line.text,
                    bbox=line.bbox,
                    confidence=line.confidence,
                    language=language,
                    paragraph_index=paragraph_index,
                    boxes=line.boxes,
                )
            )
            paragraph_index += 1
            continue
        if paragraph_lines and not _same_paragraph(paragraph_lines[-1], line, body_height):
            flush_paragraph()
        paragraph_lines.append(line)
    flush_paragraph()
    return elements


def _same_paragraph(
    previous: OcrLayoutLine,
    current: OcrLayoutLine,
    body_height: float,
) -> bool:
    vertical_gap = current.bbox[1] - previous.bbox[3]
    left_delta = abs(current.bbox[0] - previous.bbox[0])
    previous_height = previous.bbox[3] - previous.bbox[1]
    current_height = current.bbox[3] - current.bbox[1]
    height_ratio = max(previous_height, current_height) / min(
        previous_height,
        current_height,
    )
    return (
        0.0 <= vertical_gap <= max(4.0, body_height * 1.5)
        and left_delta <= max(10.0, body_height * 1.5)
        and height_ratio <= _PARAGRAPH_HEIGHT_RATIO
    )


def _body_line_height(lines: tuple[OcrLayoutLine, ...]) -> float:
    heights = sorted(line.bbox[3] - line.bbox[1] for line in lines)
    body_cluster = [heights[0]]
    for height in heights[1:]:
        cluster_height = median(body_cluster)
        if (
            height > cluster_height * _BODY_CLUSTER_GAP_RATIO
            and height > cluster_height + 2.0
        ):
            break
        body_cluster.append(height)
    return median(body_cluster)


def _table_element(cell: OcrTableCell, *, language: str) -> OcrLayoutElement:
    return OcrLayoutElement(
        kind="table_cell",
        page=cell.page,
        text=cell.text,
        bbox=cell.bbox,
        confidence=cell.confidence,
        language=language,
        table_index=cell.table_index,
        row_index=cell.row_index,
        cell_index=cell.cell_index,
        boxes=cell.boxes,
    )


def _join_box_text(boxes: tuple[OcrLayoutBox, ...], *, language: str) -> str:
    separator = " " if language.strip().lower() == "en" else ""
    return separator.join(box.text for box in boxes)


def _mean_confidence(boxes: tuple[OcrLayoutBox, ...]) -> float:
    return sum(box.confidence for box in boxes) / len(boxes)


def _box_order(box: OcrLayoutBox) -> tuple[float, float, float, int]:
    return box.bbox[1], box.bbox[0], box.bbox[3], box.box_index


def _element_order(
    element: OcrLayoutElement,
) -> tuple[float, float, int, int, int, int]:
    kind_order = {"heading": 0, "paragraph": 1, "table_cell": 2}
    return (
        element.bbox[1],
        element.bbox[0],
        kind_order[element.kind],
        element.table_index if element.table_index is not None else -1,
        element.row_index if element.row_index is not None else -1,
        element.cell_index if element.cell_index is not None else -1,
    )


def _vertical_overlap_ratio(first: BBox, second: BBox) -> float:
    overlap = max(0.0, min(first[3], second[3]) - max(first[1], second[1]))
    return overlap / max(min(first[3] - first[1], second[3] - second[1]), 1e-9)


def _quad(value: object) -> Quad:
    if not isinstance(value, tuple | list) or len(value) != 4:
        raise TypeError("quad must contain exactly four points")
    points: list[tuple[float, float]] = []
    for point in value:
        if not isinstance(point, tuple | list) or len(point) != 2:
            raise TypeError("quad points must contain exactly two finite coordinates")
        points.append(
            (
                _finite_float(point[0], field_name="quad"),
                _finite_float(point[1], field_name="quad"),
            )
        )
    if len(set(points)) != 4 or _polygon_area(points) <= 0.0:
        raise ValueError("quad must be a non-degenerate quadrilateral")
    if _segments_intersect(points[0], points[1], points[2], points[3]) or _segments_intersect(
        points[1], points[2], points[3], points[0]
    ):
        raise ValueError("quad must not self-intersect")
    return points[0], points[1], points[2], points[3]


def _bbox(value: object, *, field_name: str) -> BBox:
    if not isinstance(value, tuple | list) or len(value) != 4:
        raise TypeError(f"{field_name} must contain four finite coordinates")
    x0, y0, x1, y1 = (
        _finite_float(coordinate, field_name=field_name)
        for coordinate in value
    )
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"{field_name} must have positive width and height")
    return x0, y0, x1, y1


def _finite_float(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{field_name} must be a finite number")
    normalized = float(value)
    if not isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    return normalized


def _combined_bbox(bboxes: Iterable[BBox]) -> BBox:
    values: tuple[BBox, ...] = tuple(bboxes)
    return (
        min(bbox[0] for bbox in values),
        min(bbox[1] for bbox in values),
        max(bbox[2] for bbox in values),
        max(bbox[3] for bbox in values),
    )


def _polygon_area(points: list[tuple[float, float]]) -> float:
    return abs(
        sum(
            (x1 * y2) - (x2 * y1)
            for (x1, y1), (x2, y2) in zip(points, (*points[1:], points[0]), strict=True)
        )
    ) / 2.0


def _segments_intersect(
    first_start: tuple[float, float],
    first_end: tuple[float, float],
    second_start: tuple[float, float],
    second_end: tuple[float, float],
) -> bool:
    first_a = _orientation(first_start, first_end, second_start)
    first_b = _orientation(first_start, first_end, second_end)
    second_a = _orientation(second_start, second_end, first_start)
    second_b = _orientation(second_start, second_end, first_end)
    return first_a * first_b <= 0.0 and second_a * second_b <= 0.0


def _orientation(
    start: tuple[float, float],
    end: tuple[float, float],
    point: tuple[float, float],
) -> float:
    return (end[0] - start[0]) * (point[1] - start[1]) - (
        end[1] - start[1]
    ) * (point[0] - start[0])


def _strict_limit(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise TypeError(f"{field_name} must be a positive integer")
    return value
