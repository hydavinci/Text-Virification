from __future__ import annotations

from enum import StrEnum
from math import isfinite
from numbers import Real
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PositiveInt = Annotated[int, Field(strict=True, ge=1)]
NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
NonNegativeFloat = Annotated[float, Field(strict=True, ge=0)]
BBox = tuple[float, float, float, float]


class PdfPageKind(StrEnum):
    TEXT = "text"
    SCANNED = "scanned"
    MIXED = "mixed"


def _strict_finite_float(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{field_name} must be a finite float")
    normalized = float(value)
    if not isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    return normalized


def _strict_bbox(value: object, *, field_name: str) -> BBox:
    if not isinstance(value, tuple | list) or len(value) != 4:
        raise TypeError(f"{field_name} must contain four finite coordinates")
    x0, y0, x1, y1 = (
        _strict_finite_float(coordinate, field_name=field_name)
        for coordinate in value
    )
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"{field_name} must have positive width and height")
    return x0, y0, x1, y1


class _PdfModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PdfExtractionWarning(_PdfModel):
    page: PositiveInt
    stage: Literal["table", "image"]
    code: Literal["pdf_table_extraction_failed", "pdf_image_extraction_failed"]
    message: str


class PdfTextSpan(_PdfModel):
    text: str = Field(min_length=1)
    bbox: BBox
    font_name: str = Field(min_length=1)
    font_size: NonNegativeFloat = Field(gt=0)
    font_flags: NonNegativeInt
    color: NonNegativeInt
    span_index: NonNegativeInt

    @field_validator("bbox", mode="before")
    @classmethod
    def validate_bbox(cls, value: object) -> BBox:
        return _strict_bbox(value, field_name="bbox")

    @field_validator("font_size", mode="before")
    @classmethod
    def validate_font_size(cls, value: object) -> float:
        return _strict_finite_float(value, field_name="font_size")


class PdfTableCell(_PdfModel):
    text: str
    bbox: BBox | None
    table_index: NonNegativeInt
    row_index: NonNegativeInt
    cell_index: NonNegativeInt

    @field_validator("bbox", mode="before")
    @classmethod
    def validate_bbox(cls, value: object) -> BBox | None:
        if value is None:
            return None
        return _strict_bbox(value, field_name="bbox")


class PdfTable(_PdfModel):
    table_index: NonNegativeInt
    bbox: BBox
    row_count: PositiveInt
    column_count: PositiveInt
    rows: tuple[tuple[PdfTableCell, ...], ...]

    @field_validator("bbox", mode="before")
    @classmethod
    def validate_bbox(cls, value: object) -> BBox:
        return _strict_bbox(value, field_name="bbox")

    @model_validator(mode="after")
    def validate_shape(self) -> PdfTable:
        if len(self.rows) != self.row_count:
            raise ValueError("table row_count must match rows")
        if any(len(row) != self.column_count for row in self.rows):
            raise ValueError("table column_count must match every row")
        for row_index, row in enumerate(self.rows):
            for cell_index, cell in enumerate(row):
                if (
                    cell.table_index != self.table_index
                    or cell.row_index != row_index
                    or cell.cell_index != cell_index
                ):
                    raise ValueError("table cells must match their table coordinates")
        return self


class PdfImage(_PdfModel):
    image_index: NonNegativeInt
    xref: PositiveInt
    bbox: BBox

    @field_validator("bbox", mode="before")
    @classmethod
    def validate_bbox(cls, value: object) -> BBox:
        return _strict_bbox(value, field_name="bbox")


class OcrRequirement(_PdfModel):
    mode: Literal["required", "partial"]
    pages: tuple[PositiveInt, ...]

    @model_validator(mode="after")
    def validate_pages(self) -> OcrRequirement:
        if not self.pages or tuple(sorted(set(self.pages))) != self.pages:
            raise ValueError("OCR-required pages must be non-empty, unique, and ordered")
        return self


class PdfPageMetadata(_PdfModel):
    page: PositiveInt
    kind: PdfPageKind
    page_bbox: BBox
    text_length: NonNegativeInt
    text_density: NonNegativeFloat
    image_coverage: NonNegativeFloat = Field(le=1)
    ocr_required: bool = Field(strict=True)
    spans: tuple[PdfTextSpan, ...] = ()
    tables: tuple[PdfTable, ...] = ()
    images: tuple[PdfImage, ...] = ()

    @field_validator("page_bbox", mode="before")
    @classmethod
    def validate_page_bbox(cls, value: object) -> BBox:
        bbox = _strict_bbox(value, field_name="page_bbox")
        if bbox[0] != 0.0 or bbox[1] != 0.0:
            raise ValueError("page_bbox must be normalized to the visual origin")
        return bbox

    @field_validator("text_density", "image_coverage", mode="before")
    @classmethod
    def validate_finite_density(cls, value: object, info: object) -> float:
        field_name = getattr(info, "field_name", "value")
        return _strict_finite_float(value, field_name=field_name)

    @model_validator(mode="after")
    def validate_content_bounds(self) -> PdfPageMetadata:
        bboxes = [
            span.bbox
            for span in self.spans
        ] + [
            cell.bbox
            for table in self.tables
            for row in table.rows
            for cell in row
            if cell.bbox is not None
        ] + [image.bbox for image in self.images]
        if any(not _contains(self.page_bbox, bbox) for bbox in bboxes):
            raise ValueError("content bbox must be within page bounds")
        return self


class PdfDocumentMetadata(_PdfModel):
    pages: tuple[PdfPageMetadata, ...]
    warnings: tuple[PdfExtractionWarning, ...] = ()
    ocr_requirement: OcrRequirement | None = None

    @model_validator(mode="after")
    def validate_pages(self) -> PdfDocumentMetadata:
        expected_pages = tuple(range(1, len(self.pages) + 1))
        if tuple(page.page for page in self.pages) != expected_pages:
            raise ValueError("PDF page metadata must have ordered page numbers")
        if self.ocr_requirement is not None:
            required_pages = tuple(
                page.page for page in self.pages if page.ocr_required
            )
            if self.ocr_requirement.pages != required_pages:
                raise ValueError("OCR requirement pages must match page metadata")
        return self


class PdfResourceLimits(_PdfModel):
    max_pages: PositiveInt = 200
    max_images_per_page: PositiveInt = 200
    max_image_xrefs_per_page: PositiveInt = 100
    max_image_rectangles_per_page: PositiveInt = 500
    max_tables_per_page: PositiveInt = 50
    max_table_cells_per_page: PositiveInt = 10_000


def _contains(outer: BBox, inner: BBox) -> bool:
    return (
        outer[0] <= inner[0] <= inner[2] <= outer[2]
        and outer[1] <= inner[1] <= inner[3] <= outer[3]
    )
