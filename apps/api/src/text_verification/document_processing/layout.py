from __future__ import annotations

import re
import unicodedata
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
_BODY_CLUSTER_GAP_RATIO = 1.15
_PARAGRAPH_HEIGHT_RATIO = 1.25
_MIN_TABLE_GAP_HEIGHT_RATIO = 1.5
_MAX_TABLE_ROW_GAP_HEIGHT_RATIO = 4.0
_NUMERIC_CJK_LIST_MARKER = re.compile(
    r"^(?:\((?P<parenthesized>[0-9一二三四五六七八九十百千]+)\)"
    r"|(?P<suffixed>[0-9一二三四五六七八九十百千]+)[.)、])$"
)
_ALPHABETIC_LIST_MARKER = re.compile(
    r"^(?:\((?P<parenthesized>[A-Za-z])\)"
    r"|(?P<lowercase>[a-z])[.)、]"
    r"|(?P<uppercase_close>[A-Z])\))$"
)
_LIST_BULLETS = frozenset("•●▪◦‣⁃∙·○◆◇■□▲△※-–—")
_CJK_NUMERAL_VALUES = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


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
        if (
            not _rows_have_stable_columns(rows)
            or _is_marker_list(rows)
            or _looks_like_aligned_prose(rows)
            or (len(rows) == 2 and not _has_strong_two_row_evidence(rows))
        ):
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
        min(
            abs(first_box.bbox[0] - second_box.bbox[0]),
            abs(_bbox_center_x(first_box.bbox) - _bbox_center_x(second_box.bbox)),
        )
        > alignment_tolerance
        for first_box, second_box in zip(first.boxes, second.boxes, strict=True)
    ):
        return False
    return _row_has_stable_baseline(first, typical_height) and _row_has_stable_baseline(
        second,
        typical_height,
    )


def _rows_have_stable_columns(rows: list[OcrLayoutLine]) -> bool:
    typical_height = median(
        box.height
        for row in rows
        for box in row.boxes
    )
    alignment_tolerance = max(4.0, typical_height * 0.75)
    for column_index in range(len(rows[0].boxes)):
        left_anchors = [
            row.boxes[column_index].bbox[0]
            for row in rows
        ]
        center_anchors = [
            _bbox_center_x(row.boxes[column_index].bbox)
            for row in rows
        ]
        if min(
            max(left_anchors) - min(left_anchors),
            max(center_anchors) - min(center_anchors),
        ) > alignment_tolerance:
            return False
    return all(_row_has_stable_baseline(row, typical_height) for row in rows)


def _is_marker_list(rows: list[OcrLayoutLine]) -> bool:
    markers = [_normalized_list_marker(row.boxes[0].text) for row in rows]
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
    marker_values = [marker for marker in markers if marker is not None]
    if all(marker[0] == "bullet" for marker in marker_values):
        return True
    if len({marker[0] for marker in marker_values}) != 1:
        return False
    values = [marker[1] for marker in marker_values if marker[1] is not None]
    if len(values) != len(marker_values):
        return False
    return values == list(range(values[0], values[0] + len(values)))


def _normalized_list_marker(text: str) -> tuple[str, int | None] | None:
    normalized = unicodedata.normalize("NFKC", text).strip()
    if normalized in _LIST_BULLETS:
        return "bullet", None
    numeric_match = _NUMERIC_CJK_LIST_MARKER.fullmatch(normalized)
    if numeric_match is not None:
        token = numeric_match.group("parenthesized") or numeric_match.group("suffixed")
        value = _list_sequence_value(token)
        return ("numeric", value) if value is not None else None
    alphabetic_match = _ALPHABETIC_LIST_MARKER.fullmatch(normalized)
    if alphabetic_match is None:
        return None
    token = (
        alphabetic_match.group("parenthesized")
        or alphabetic_match.group("lowercase")
        or alphabetic_match.group("uppercase_close")
    )
    return "alphabetic", ord(token.casefold()) - ord("a") + 1


def _list_sequence_value(token: str) -> int | None:
    if token.isdecimal():
        return int(token)
    if token in _CJK_NUMERAL_VALUES:
        return _CJK_NUMERAL_VALUES[token]
    if "十" not in token or token.count("十") != 1:
        return None
    left, right = token.split("十")
    tens = _CJK_NUMERAL_VALUES.get(left, 1) if left else 1
    ones = _CJK_NUMERAL_VALUES.get(right, 0) if right else 0
    return tens * 10 + ones


def _row_has_stable_baseline(
    row: OcrLayoutLine,
    typical_height: float,
) -> bool:
    baselines = [box.baseline for box in row.boxes]
    return max(baselines) - min(baselines) <= max(2.0, typical_height * 0.35)


def _has_strong_two_row_evidence(rows: list[OcrLayoutLine]) -> bool:
    typical_height = median(box.height for row in rows for box in row.boxes)
    row_heights = [row.bbox[3] - row.bbox[1] for row in rows]
    if max(row_heights) - min(row_heights) > max(2.0, typical_height * 0.25):
        return False
    first_gaps = _row_gaps(rows[0])
    second_gaps = _row_gaps(rows[1])
    if any(
        abs(first_gap - second_gap)
        > max(typical_height * 1.5, median((first_gap, second_gap)) * 0.35)
        for first_gap, second_gap in zip(first_gaps, second_gaps, strict=True)
    ):
        return False
    return all(
        _looks_like_compact_table_value(row.boxes[0].text)
        for row in rows
    )


def _row_gaps(row: OcrLayoutLine) -> tuple[float, ...]:
    return tuple(
        right.bbox[0] - left.bbox[2]
        for left, right in zip(row.boxes, row.boxes[1:], strict=False)
    )


def _looks_like_aligned_prose(rows: list[OcrLayoutLine]) -> bool:
    first_column = [row.boxes[0].text.strip() for row in rows]
    second_column = [row.boxes[1].text.strip() for row in rows]
    if all(_looks_like_table_code(text) for text in first_column):
        return False
    first_is_labels = all(
        text.replace(" ", "").isalpha() and len(text.replace(" ", "")) >= 2
        for text in first_column
    )
    second_is_prose = all(
        any(character.isspace() for character in text)
        or text.replace(" ", "").isalpha()
        or len(text) >= 12
        for text in second_column
    )
    return first_is_labels and second_is_prose


def _looks_like_table_code(text: str) -> bool:
    normalized = unicodedata.normalize("NFKC", text).strip()
    core = normalized[:-1] if normalized.endswith(".") else normalized
    return (
        1 <= len(normalized) <= 12
        and not any(character.isspace() for character in normalized)
        and (
            (any(character.isdigit() for character in core) and core.isalnum())
            or (
                normalized.endswith(".")
                and len(core) == 1
                and core.isalpha()
                and core.isupper()
            )
        )
    )


def _looks_like_compact_table_value(text: str) -> bool:
    normalized = unicodedata.normalize("NFKC", text).strip()
    return (
        _looks_like_table_code(normalized)
        or (
            1 <= len(normalized) <= 3
            and not any(character.isspace() for character in normalized)
            and _normalized_list_marker(normalized) is None
        )
    )


def _bbox_center_x(bbox: BBox) -> float:
    return (bbox[0] + bbox[2]) / 2.0


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
    ordered = sorted(
        lines,
        key=lambda line: (line.bbox[3] - line.bbox[1], line.line_index),
    )
    clusters: list[list[OcrLayoutLine]] = [[ordered[0]]]
    for line in ordered[1:]:
        height = line.bbox[3] - line.bbox[1]
        cluster_heights = [
            member.bbox[3] - member.bbox[1]
            for member in clusters[-1]
        ]
        cluster_height = median(cluster_heights)
        if (
            height > cluster_height * _BODY_CLUSTER_GAP_RATIO
            and height > cluster_height + 2.0
        ):
            clusters.append([line])
        else:
            clusters[-1].append(line)
    largest_population = max(len(cluster) for cluster in clusters)
    contenders = [
        cluster
        for cluster in clusters
        if len(cluster) == largest_population
    ]
    if len(contenders) == 1:
        body_cluster = contenders[0]
    elif largest_population == 1:
        body_cluster = min(contenders, key=_cluster_height)
    else:
        body_cluster = max(contenders, key=_cluster_height)
    return _cluster_height(body_cluster)


def _cluster_height(cluster: list[OcrLayoutLine]) -> float:
    return median(line.bbox[3] - line.bbox[1] for line in cluster)


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
