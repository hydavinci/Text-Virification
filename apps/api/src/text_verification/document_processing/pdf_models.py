from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PdfPageKind(StrEnum):
    TEXT = "text"
    SCANNED = "scanned"
    MIXED = "mixed"


class PdfExtractionWarning(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    page: int = Field(ge=1)
    stage: Literal["table", "image"]
    code: Literal["pdf_table_extraction_failed", "pdf_image_extraction_failed"]
    message: str


class PdfTextSpan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    bbox: tuple[float, float, float, float]
    font_name: str
    font_size: float = Field(ge=0)
    font_flags: int
    color: int
    span_index: int = Field(ge=0)


class PdfTableCell(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    bbox: tuple[float, float, float, float]
    table_index: int = Field(ge=0)
    row_index: int = Field(ge=0)
    cell_index: int = Field(ge=0)


class PdfImage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    image_index: int = Field(ge=0)
    xref: int = Field(ge=0)
    bbox: tuple[float, float, float, float]


class PdfPageMetadata(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    page: int = Field(ge=1)
    kind: PdfPageKind
    text_length: int = Field(ge=0)
    text_density: float = Field(ge=0)
    image_coverage: float = Field(ge=0, le=1)
    ocr_required: bool


class PdfPageExtraction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    metadata: PdfPageMetadata
    spans: tuple[PdfTextSpan, ...] = ()
    table_cells: tuple[PdfTableCell, ...] = ()
    images: tuple[PdfImage, ...] = ()
    warnings: tuple[PdfExtractionWarning, ...] = ()


class PdfDocumentMetadata(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    pages: tuple[PdfPageMetadata, ...]
    warnings: tuple[PdfExtractionWarning, ...] = ()
