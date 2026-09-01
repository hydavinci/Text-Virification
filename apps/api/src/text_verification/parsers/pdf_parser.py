from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

import pymupdf

from text_verification.compatibility.adapters import source_version_for_file
from text_verification.document_processing.pdf_classifier import classify_page
from text_verification.document_processing.pdf_models import (
    PdfDocumentMetadata,
    PdfExtractionWarning,
    PdfImage,
    PdfPageExtraction,
    PdfTableCell,
    PdfTextSpan,
)
from text_verification.domain.documents import DocumentModel, FileType, TextBlock
from text_verification.parsers.errors import ParserError

_PARSER_NAME = "pymupdf-pdf"
_PARSER_VERSION = "1"
_TABLE_IMAGE_EXTRACTION_ERRORS = (RuntimeError, ValueError)
_OPEN_ERRORS = (pymupdf.FileDataError, OSError, RuntimeError)
_PYMUPDF: Any = pymupdf


@dataclass(frozen=True)
class PdfParser:
    supported_type: FileType = FileType.PDF

    def parse(self, source_path: Path) -> DocumentModel:
        source_version = source_version_for_file(source_path)
        try:
            pdf: Any = _PYMUPDF.open(source_path)
        except _OPEN_ERRORS as error:
            raise ParserError("PDF source could not be read.") from error

        try:
            if pdf.is_encrypted and not pdf.authenticate(""):
                raise ParserError("PDF source is encrypted and cannot be read.")

            page_extractions = tuple(
                _extract_page(page, page_number)
                for page_number, page in enumerate(pdf, start=1)
            )
        finally:
            pdf.close()

        blocks, text = _canonical_blocks(page_extractions)
        metadata = PdfDocumentMetadata(
            pages=tuple(extraction.metadata for extraction in page_extractions),
            warnings=tuple(
                warning
                for extraction in page_extractions
                for warning in extraction.warnings
            ),
        )
        return DocumentModel(
            document_id=uuid5(
                NAMESPACE_URL,
                f"document:{FileType.PDF.value}:{source_path.name}:{source_version}",
            ),
            source_version=source_version,
            file_type=FileType.PDF,
            source_name=source_path.name,
            text=text,
            blocks=blocks,
            parser_name=_PARSER_NAME,
            parser_version=_PARSER_VERSION,
            metadata={"pdf": metadata.model_dump(mode="json")},
        )


def _extract_page(page: Any, page_number: int) -> PdfPageExtraction:
    images, image_warnings = _extract_images(page, page_number)
    table_cells, table_rectangles, table_warnings = _extract_table_cells(page, page_number)
    spans = _extract_spans(page, table_rectangles)
    metadata = classify_page(
        page,
        page_number,
        image_rectangles=(image.bbox for image in images),
    )
    return PdfPageExtraction(
        metadata=metadata,
        spans=tuple(spans),
        table_cells=tuple(table_cells),
        images=tuple(images),
        warnings=tuple((*image_warnings, *table_warnings)),
    )


def _extract_spans(
    page: Any,
    table_rectangles: list[tuple[float, float, float, float]],
) -> list[PdfTextSpan]:
    spans: list[PdfTextSpan] = []
    span_index = 0
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = _normalize_text(str(span.get("text", "")))
                bbox = _bbox(span["bbox"])
                if not text or any(
                    _intersects(bbox, table_bbox) for table_bbox in table_rectangles
                ):
                    continue
                spans.append(
                    PdfTextSpan(
                        text=text,
                        bbox=bbox,
                        font_name=str(span.get("font", "")),
                        font_size=float(span.get("size", 0.0)),
                        font_flags=int(span.get("flags", 0)),
                        color=int(span.get("color", 0)),
                        span_index=span_index,
                    )
                )
                span_index += 1
    return spans


def _extract_table_cells(
    page: Any,
    page_number: int,
) -> tuple[
    list[PdfTableCell],
    list[tuple[float, float, float, float]],
    list[PdfExtractionWarning],
]:
    try:
        tables = page.find_tables().tables
    except _TABLE_IMAGE_EXTRACTION_ERRORS:
        return [], [], [_warning(page_number, "table")]

    cells: list[PdfTableCell] = []
    table_rectangles: list[tuple[float, float, float, float]] = []
    try:
        for table_index, table in enumerate(tables):
            table_rectangles.append(_bbox(table.bbox))
            rows = table.extract()
            for row_index, row in enumerate(rows):
                for cell_index, cell_text in enumerate(row):
                    text = _normalize_text(cell_text or "")
                    if not text:
                        continue
                    cell_bbox = table.rows[row_index].cells[cell_index]
                    if cell_bbox is None:
                        continue
                    cells.append(
                        PdfTableCell(
                            text=text,
                            bbox=_bbox(cell_bbox),
                            table_index=table_index,
                            row_index=row_index,
                            cell_index=cell_index,
                        )
                    )
    except _TABLE_IMAGE_EXTRACTION_ERRORS:
        return [], [], [_warning(page_number, "table")]
    return cells, table_rectangles, []


def _extract_images(
    page: Any,
    page_number: int,
) -> tuple[list[PdfImage], list[PdfExtractionWarning]]:
    try:
        images: list[PdfImage] = []
        image_index = 0
        seen_xrefs: set[int] = set()
        for image in page.get_images(full=True):
            xref = int(image[0])
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)
            for rectangle in page.get_image_rects(xref):
                if rectangle.is_empty:
                    continue
                images.append(
                    PdfImage(
                        image_index=image_index,
                        xref=xref,
                        bbox=_bbox(rectangle),
                    )
                )
                image_index += 1
    except _TABLE_IMAGE_EXTRACTION_ERRORS:
        return [], [_warning(page_number, "image")]
    return images, []


def _canonical_blocks(
    page_extractions: tuple[PdfPageExtraction, ...],
) -> tuple[list[TextBlock], str]:
    extracted_blocks: list[_ExtractedBlock] = []
    for extraction in page_extractions:
        page_number = extraction.metadata.page
        if extraction.spans and not extraction.table_cells and not extraction.images:
            extracted_blocks.append(_page_block(extraction.spans, page_number))
        else:
            extracted_blocks.extend(_span_blocks(extraction.spans, page_number))
        extracted_blocks.extend(_table_blocks(extraction.table_cells, page_number))
        extracted_blocks.extend(_image_blocks(extraction.images, page_number))

    ordered = sorted(
        extracted_blocks,
        key=lambda block: (
            block.page,
            block.bbox[1],
            block.bbox[0],
            _kind_order(block.kind),
            block.ordinal,
        ),
    )
    text_parts: list[str] = []
    blocks: list[TextBlock] = []
    cursor = 0
    for extracted in ordered:
        if extracted.text:
            if text_parts:
                text_parts.append("\n")
                cursor += 1
            start = cursor
            text_parts.append(extracted.text)
            cursor += len(extracted.text)
        else:
            start = cursor
        blocks.append(
            TextBlock(
                block_id=extracted.block_id,
                kind=extracted.kind,
                text=extracted.text,
                global_start=start,
                global_end=cursor,
                block_start=0,
                block_end=len(extracted.text),
                page=extracted.page,
                paragraph_index=extracted.paragraph_index,
                table_index=extracted.table_index,
                row_index=extracted.row_index,
                cell_index=extracted.cell_index,
                bbox=extracted.bbox,
                parent_id=None,
                style=extracted.style,
                source_locator=extracted.source_locator,
            )
        )
    return blocks, "".join(text_parts)


@dataclass(frozen=True)
class _ExtractedBlock:
    block_id: str
    kind: Literal["paragraph", "table_cell", "image"]
    text: str
    page: int
    bbox: tuple[float, float, float, float]
    ordinal: int
    paragraph_index: int | None
    table_index: int | None
    row_index: int | None
    cell_index: int | None
    style: dict[str, object]
    source_locator: dict[str, object]


def _page_block(spans: tuple[PdfTextSpan, ...], page: int) -> _ExtractedBlock:
    first = spans[0]
    return _ExtractedBlock(
        block_id=f"page-{page}",
        kind="paragraph",
        text="\n".join(span.text for span in spans),
        page=page,
        bbox=(
            min(span.bbox[0] for span in spans),
            min(span.bbox[1] for span in spans),
            max(span.bbox[2] for span in spans),
            max(span.bbox[3] for span in spans),
        ),
        ordinal=0,
        paragraph_index=0,
        table_index=None,
        row_index=None,
        cell_index=None,
        style={
            "font": {
                "name": first.font_name,
                "size": first.font_size,
                "flags": first.font_flags,
                "color": first.color,
            },
            "spans": [span.model_dump(mode="json") for span in spans],
        },
        source_locator={"locator_kind": "page", "page": page},
    )


def _span_blocks(spans: tuple[PdfTextSpan, ...], page: int) -> list[_ExtractedBlock]:
    return [
        _ExtractedBlock(
            block_id=f"pdf-page-{page}-paragraph-{span.span_index}",
            kind="paragraph",
            text=span.text,
            page=page,
            bbox=span.bbox,
            ordinal=span.span_index,
            paragraph_index=span.span_index,
            table_index=None,
            row_index=None,
            cell_index=None,
            style={
                "font": {
                    "name": span.font_name,
                    "size": span.font_size,
                    "flags": span.font_flags,
                    "color": span.color,
                }
            },
            source_locator={
                "locator_kind": "pdf_span",
                "page": page,
                "span_index": span.span_index,
                "bbox": list(span.bbox),
            },
        )
        for span in spans
    ]


def _table_blocks(cells: tuple[PdfTableCell, ...], page: int) -> list[_ExtractedBlock]:
    return [
        _ExtractedBlock(
            block_id=(
                f"pdf-page-{page}-table-{cell.table_index}-row-{cell.row_index}"
                f"-cell-{cell.cell_index}"
            ),
            kind="table_cell",
            text=cell.text,
            page=page,
            bbox=cell.bbox,
            ordinal=cell.row_index * 10_000 + cell.cell_index,
            paragraph_index=None,
            table_index=cell.table_index,
            row_index=cell.row_index,
            cell_index=cell.cell_index,
            style={},
            source_locator={
                "locator_kind": "table_cell",
                "page": page,
                "table_index": cell.table_index,
                "row_index": cell.row_index,
                "cell_index": cell.cell_index,
                "bbox": list(cell.bbox),
            },
        )
        for cell in cells
    ]


def _image_blocks(images: tuple[PdfImage, ...], page: int) -> list[_ExtractedBlock]:
    return [
        _ExtractedBlock(
            block_id=f"pdf-page-{page}-image-{image.image_index}",
            kind="image",
            text="",
            page=page,
            bbox=image.bbox,
            ordinal=image.image_index,
            paragraph_index=None,
            table_index=None,
            row_index=None,
            cell_index=None,
            style={},
            source_locator={
                "locator_kind": "image",
                "page": page,
                "image_index": image.image_index,
                "xref": image.xref,
                "bbox": list(image.bbox),
            },
        )
        for image in images
    ]


def _warning(page: int, stage: Literal["table", "image"]) -> PdfExtractionWarning:
    if stage == "table":
        return PdfExtractionWarning(
            page=page,
            stage=stage,
            code="pdf_table_extraction_failed",
            message="PyMuPDF table extraction failed.",
        )
    return PdfExtractionWarning(
        page=page,
        stage=stage,
        code="pdf_image_extraction_failed",
        message="PyMuPDF image extraction failed.",
    )


def _bbox(rectangle: Any) -> tuple[float, float, float, float]:
    if isinstance(rectangle, tuple | list):
        return tuple(float(value) for value in rectangle)  # type: ignore[return-value]
    return (
        float(rectangle.x0),
        float(rectangle.y0),
        float(rectangle.x1),
        float(rectangle.y1),
    )


def _intersects(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> bool:
    return (
        first[0] < second[2]
        and first[2] > second[0]
        and first[1] < second[3]
        and first[3] > second[1]
    )


def _normalize_text(text: str) -> str:
    return " ".join(text.split())


def _kind_order(kind: Literal["paragraph", "table_cell", "image"]) -> int:
    return {"paragraph": 0, "table_cell": 1, "image": 2}[kind]
