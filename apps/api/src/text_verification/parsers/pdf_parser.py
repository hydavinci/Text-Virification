from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

import pymupdf

from text_verification.compatibility.adapters import source_version_for_file
from text_verification.document_processing.pdf_classifier import classify_page
from text_verification.document_processing.pdf_models import (
    OcrRequirement,
    PdfDocumentMetadata,
    PdfExtractionWarning,
    PdfImage,
    PdfPageMetadata,
    PdfResourceLimits,
    PdfTable,
    PdfTableCell,
    PdfTextSpan,
)
from text_verification.domain.documents import DocumentMetadata, DocumentModel, FileType, TextBlock
from text_verification.parsers.errors import ParserError, PdfResourceLimitError

_PARSER_NAME = "pymupdf-pdf"
_PARSER_VERSION = "2"
_PYMUPDF: Any = pymupdf


@dataclass(frozen=True)
class PdfParser:
    supported_type: FileType = FileType.PDF
    limits: PdfResourceLimits = field(default_factory=PdfResourceLimits)

    def parse(self, source_path: Path) -> DocumentModel:
        source_version = source_version_for_file(source_path)
        try:
            pdf: Any = _PYMUPDF.open(source_path)
        except (pymupdf.FileDataError, OSError) as error:
            raise ParserError("PDF source could not be read.") from error
        try:
            if pdf.is_encrypted and not pdf.authenticate(""):
                raise ParserError("PDF source is encrypted and cannot be read.")
            if pdf.page_count > self.limits.max_pages:
                raise PdfResourceLimitError(
                    limit="max_pages",
                    maximum=self.limits.max_pages,
                    actual=pdf.page_count,
                )
            extracted_pages = tuple(
                _extract_page(page, page_number, self.limits)
                for page_number, page in enumerate(pdf, start=1)
            )
        finally:
            pdf.close()

        pages = tuple(extracted.metadata for extracted in extracted_pages)
        metadata = PdfDocumentMetadata(
            pages=pages,
            warnings=tuple(
                warning
                for extracted in extracted_pages
                for warning in extracted.warnings
            ),
            ocr_requirement=_ocr_requirement(pages),
        )
        blocks, text = _canonical_blocks(pages)
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
            metadata=DocumentMetadata(pdf=metadata),
        )


def _extract_page(
    page: Any,
    page_number: int,
    limits: PdfResourceLimits,
) -> _ExtractedPage:
    geometry = _PageGeometry(
        page_bbox=_bbox(page.rect),
        rotation_matrix=page.rotation_matrix,
    )
    raw_spans = _extract_raw_spans(page, geometry)
    images, image_warnings = _extract_images(page, page_number, limits, geometry)
    classification = classify_page(
        page,
        page_number,
        image_rectangles=(image.bbox for image in images),
    )
    tables, table_warnings = _extract_tables(page, page_number, limits)
    tables = _normalize_tables(tables, geometry)
    spans = _extract_spans(raw_spans, tables)
    return _ExtractedPage(
        metadata=PdfPageMetadata(
            page=page_number,
            kind=classification.kind,
            page_bbox=geometry.page_bbox,
            text_length=classification.text_length,
            text_density=classification.text_density,
            image_coverage=classification.image_coverage,
            ocr_required=classification.ocr_required,
            spans=tuple(spans),
            tables=tuple(tables),
            images=tuple(images),
        ),
        warnings=tuple((*image_warnings, *table_warnings)),
    )


def _extract_images(
    page: Any,
    page_number: int,
    limits: PdfResourceLimits,
    geometry: _PageGeometry,
) -> tuple[list[PdfImage], list[PdfExtractionWarning]]:
    try:
        raw_images = page.get_images(full=True)
    except pymupdf.FileDataError:
        return [], [_warning(page_number, "image")]
    if len(raw_images) > limits.max_images_per_page:
        raise PdfResourceLimitError(
            limit="max_images_per_page",
            maximum=limits.max_images_per_page,
            actual=len(raw_images),
        )
    xrefs = tuple(dict.fromkeys(int(image[0]) for image in raw_images))
    if len(xrefs) > limits.max_image_xrefs_per_page:
        raise PdfResourceLimitError(
            limit="max_image_xrefs_per_page",
            maximum=limits.max_image_xrefs_per_page,
            actual=len(xrefs),
        )
    images: list[PdfImage] = []
    rectangle_count = 0
    for xref in xrefs:
        try:
            rectangles = page.get_image_rects(xref)
        except pymupdf.FileDataError:
            return images, [_warning(page_number, "image")]
        rectangle_count += len(rectangles)
        if rectangle_count > limits.max_image_rectangles_per_page:
            raise PdfResourceLimitError(
                limit="max_image_rectangles_per_page",
                maximum=limits.max_image_rectangles_per_page,
                actual=rectangle_count,
            )
        for rectangle in rectangles:
            bbox = _normalized_bbox(rectangle, geometry)
            if bbox is None:
                continue
            images.append(PdfImage(image_index=len(images), xref=xref, bbox=bbox))
    return images, []


def _extract_tables(
    page: Any,
    page_number: int,
    limits: PdfResourceLimits,
) -> tuple[list[Any], list[PdfExtractionWarning]]:
    try:
        found_tables = page.find_tables().tables
    except pymupdf.FileDataError:
        return [], [_warning(page_number, "table")]
    if len(found_tables) > limits.max_tables_per_page:
        raise PdfResourceLimitError(
            limit="max_tables_per_page",
            maximum=limits.max_tables_per_page,
            actual=len(found_tables),
        )
    tables: list[Any] = []
    cell_count = 0
    for table_index, table in enumerate(found_tables):
        rows = table.rows
        cell_count += sum(len(row.cells) for row in rows)
        if cell_count > limits.max_table_cells_per_page:
            raise PdfResourceLimitError(
                limit="max_table_cells_per_page",
                maximum=limits.max_table_cells_per_page,
                actual=cell_count,
            )
        try:
            extracted_rows = table.extract()
        except pymupdf.FileDataError:
            return tables, [_warning(page_number, "table")]
        column_count = max((len(row.cells) for row in rows), default=0)
        if not rows or not column_count:
            continue
        normalized_rows: list[tuple[tuple[str, object | None], ...]] = []
        for row_index, row in enumerate(rows):
            extracted_row = extracted_rows[row_index] if row_index < len(extracted_rows) else []
            cells: list[tuple[str, object | None]] = []
            for cell_index in range(column_count):
                raw_bbox = row.cells[cell_index] if cell_index < len(row.cells) else None
                raw_text = (
                    extracted_row[cell_index]
                    if cell_index < len(extracted_row)
                    else ""
                )
                cells.append((_normalize_block_text(raw_text or ""), raw_bbox))
            normalized_rows.append(tuple(cells))
        tables.append((table_index, table.bbox, tuple(normalized_rows)))
    return tables, []


def _normalize_tables(
    raw_tables: list[Any],
    geometry: _PageGeometry,
) -> list[PdfTable]:
    tables: list[PdfTable] = []
    for table_index, table_bbox, raw_rows in raw_tables:
        normalized_table_bbox = _normalized_bbox(table_bbox, geometry)
        if normalized_table_bbox is None:
            continue
        rows: list[tuple[PdfTableCell, ...]] = []
        for row_index, raw_row in enumerate(raw_rows):
            rows.append(
                tuple(
                    PdfTableCell(
                        text=text,
                        bbox=_normalized_bbox(bbox, geometry) if bbox is not None else None,
                        table_index=table_index,
                        row_index=row_index,
                        cell_index=cell_index,
                    )
                    for cell_index, (text, bbox) in enumerate(raw_row)
                )
            )
        tables.append(
            PdfTable(
                table_index=table_index,
                bbox=normalized_table_bbox,
                row_count=len(rows),
                column_count=len(rows[0]),
                rows=tuple(rows),
            )
        )
    return tables


def _extract_raw_spans(page: Any, geometry: _PageGeometry) -> list[_RawSpan]:
    raw_spans: list[_RawSpan] = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for raw_span in line.get("spans", []):
                text = _normalize_inline_text(str(raw_span.get("text", "")))
                bbox = _normalized_bbox(raw_span["bbox"], geometry)
                if not text or bbox is None:
                    continue
                raw_spans.append(_RawSpan(text=text, bbox=bbox, raw=raw_span))
    raw_spans.sort(
        key=lambda item: (
            item.bbox[1],
            item.bbox[0],
            item.bbox[3],
            item.bbox[2],
        )
    )
    return raw_spans


def _extract_spans(raw_spans: list[_RawSpan], tables: list[PdfTable]) -> list[PdfTextSpan]:
    return [
        PdfTextSpan(
            text=raw_span.text,
            bbox=raw_span.bbox,
            font_name=str(raw_span.raw.get("font", "")) or "unknown",
            font_size=float(_as_any(raw_span.raw.get("size", 0.0))),
            font_flags=int(_as_any(raw_span.raw.get("flags", 0))),
            color=int(_as_any(raw_span.raw.get("color", 0))),
            span_index=index,
        )
        for index, raw_span in enumerate(raw_spans)
        if not _is_table_span(raw_span.text, raw_span.bbox, tables)
    ]


def _is_table_span(
    text: str,
    bbox: tuple[float, float, float, float],
    tables: list[PdfTable],
) -> bool:
    comparable_text = _comparison_text(text)
    return any(
        cell.text
        and cell.bbox is not None
        and _intersects(bbox, cell.bbox)
        and comparable_text in _comparison_text(cell.text)
        for table in tables
        for row in table.rows
        for cell in row
    )


def _canonical_blocks(pages: tuple[PdfPageMetadata, ...]) -> tuple[list[TextBlock], str]:
    extracted: list[_ExtractedBlock] = []
    for page in pages:
        visual_lines = _visual_lines(page.spans)
        if visual_lines and not page.tables and not page.images:
            extracted.append(_page_block(page.page, visual_lines))
        else:
            extracted.extend(_line_blocks(page.page, visual_lines))
        extracted.extend(_table_blocks(page.page, page.tables))
        extracted.extend(_image_blocks(page.page, page.images))

    ordered = sorted(
        extracted,
        key=lambda item: (
            item.page,
            item.bbox[1],
            item.bbox[0],
            _kind_order(item.kind),
            item.ordinal,
        ),
    )
    text_parts: list[str] = []
    blocks: list[TextBlock] = []
    cursor = 0
    for item in ordered:
        start = cursor
        if item.text:
            if text_parts:
                text_parts.append("\n")
                cursor += 1
                start = cursor
            text_parts.append(item.text)
            cursor += len(item.text)
        blocks.append(
            TextBlock(
                block_id=item.block_id,
                kind=item.kind,
                text=item.text,
                global_start=start,
                global_end=cursor,
                block_start=0,
                block_end=len(item.text),
                page=item.page,
                paragraph_index=item.paragraph_index,
                table_index=item.table_index,
                row_index=item.row_index,
                cell_index=item.cell_index,
                bbox=item.bbox,
                parent_id=None,
                style=item.style,
                source_locator=item.source_locator,
            )
        )
    return blocks, "".join(text_parts)


@dataclass(frozen=True)
class _VisualLine:
    spans: tuple[PdfTextSpan, ...]
    bbox: tuple[float, float, float, float]

    @property
    def text(self) -> str:
        return "".join(span.text for span in self.spans)


@dataclass(frozen=True)
class _RawSpan:
    text: str
    bbox: tuple[float, float, float, float]
    raw: dict[str, object]


@dataclass(frozen=True)
class _ExtractedPage:
    metadata: PdfPageMetadata
    warnings: tuple[PdfExtractionWarning, ...]


@dataclass(frozen=True)
class _PageGeometry:
    page_bbox: tuple[float, float, float, float]
    rotation_matrix: Any


def _visual_lines(spans: tuple[PdfTextSpan, ...]) -> list[_VisualLine]:
    grouped: list[list[PdfTextSpan]] = []
    for span in spans:
        if not grouped or not _same_visual_line(grouped[-1], span):
            grouped.append([span])
        else:
            grouped[-1].append(span)
    return [
        _VisualLine(
            spans=tuple(sorted(line, key=lambda span: (span.bbox[0], span.bbox[1]))),
            bbox=_combined_bbox(span.bbox for span in line),
        )
        for line in grouped
    ]


def _same_visual_line(line: list[PdfTextSpan], span: PdfTextSpan) -> bool:
    current = _combined_bbox(item.bbox for item in line)
    overlap = min(current[3], span.bbox[3]) - max(current[1], span.bbox[1])
    height = min(current[3] - current[1], span.bbox[3] - span.bbox[1])
    return overlap > 0 and overlap >= height * 0.5


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


def _page_block(page: int, lines: list[_VisualLine]) -> _ExtractedBlock:
    text, segments = _lines_text_and_segments(lines)
    first = lines[0].spans[0]
    return _ExtractedBlock(
        block_id=f"page-{page}",
        kind="paragraph",
        text=text,
        page=page,
        bbox=_combined_bbox(line.bbox for line in lines),
        ordinal=0,
        paragraph_index=0,
        table_index=None,
        row_index=None,
        cell_index=None,
        style={
            "font": _font_style(first),
            "spans": [
                span.model_dump(mode="json")
                for line in lines
                for span in line.spans
            ],
        },
        source_locator={"locator_kind": "page", "page": page, "segments": segments},
    )


def _line_blocks(page: int, lines: list[_VisualLine]) -> list[_ExtractedBlock]:
    return [
        _ExtractedBlock(
            block_id=f"pdf-page-{page}-line-{line_index}",
            kind="paragraph",
            text=line.text,
            page=page,
            bbox=line.bbox,
            ordinal=line_index,
            paragraph_index=line_index,
            table_index=None,
            row_index=None,
            cell_index=None,
            style={
                "font": _font_style(line.spans[0]),
                "spans": [span.model_dump(mode="json") for span in line.spans],
            },
            source_locator={
                "locator_kind": "pdf_line",
                "page": page,
                "line_index": line_index,
                "segments": _line_segments(line.spans, 0),
            },
        )
        for line_index, line in enumerate(lines)
    ]


def _table_blocks(page: int, tables: tuple[PdfTable, ...]) -> list[_ExtractedBlock]:
    return [
        _ExtractedBlock(
            block_id=f"pdf-page-{page}-table-{cell.table_index}-row-{cell.row_index}-cell-{cell.cell_index}",
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
                "segments": _line_segments_from_text(cell.text, cell.bbox),
            },
        )
        for table in tables
        for row in table.rows
        for cell in row
        if cell.text and cell.bbox is not None
    ]


def _image_blocks(page: int, images: tuple[PdfImage, ...]) -> list[_ExtractedBlock]:
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


def _lines_text_and_segments(lines: list[_VisualLine]) -> tuple[str, list[dict[str, object]]]:
    text_parts: list[str] = []
    segments: list[dict[str, object]] = []
    cursor = 0
    for line_index, line in enumerate(lines):
        if line_index:
            text_parts.append("\n")
            cursor += 1
        line_text = line.text
        text_parts.append(line_text)
        segments.extend(_line_segments(line.spans, cursor))
        cursor += len(line_text)
    return "".join(text_parts), segments


def _line_segments(
    spans: tuple[PdfTextSpan, ...],
    start: int,
) -> list[dict[str, object]]:
    cursor = start
    segments: list[dict[str, object]] = []
    for span in spans:
        end = cursor + len(span.text)
        segments.append(
            {
                "start": cursor,
                "end": end,
                "text": span.text,
                "bbox": list(span.bbox),
            }
        )
        cursor = end
    return segments


def _line_segments_from_text(
    text: str,
    bbox: tuple[float, float, float, float],
) -> list[dict[str, object]]:
    return [{"start": 0, "end": len(text), "text": text, "bbox": list(bbox)}]


def _font_style(span: PdfTextSpan) -> dict[str, object]:
    return {
        "name": span.font_name,
        "size": span.font_size,
        "flags": span.font_flags,
        "color": span.color,
    }


def _ocr_requirement(pages: tuple[PdfPageMetadata, ...]) -> OcrRequirement | None:
    required_pages = tuple(page.page for page in pages if page.ocr_required)
    if not required_pages:
        return None
    has_native_text = any(page.text_length > 0 for page in pages)
    return OcrRequirement(
        mode="partial" if has_native_text else "required",
        pages=required_pages,
    )


def _warning(page: int, stage: Literal["table", "image"]) -> PdfExtractionWarning:
    if stage == "table":
        return PdfExtractionWarning(
            page=page,
            stage="table",
            code="pdf_table_extraction_failed",
            message="PyMuPDF table extraction failed.",
        )
    return PdfExtractionWarning(
        page=page,
        stage="image",
        code="pdf_image_extraction_failed",
        message="PyMuPDF image extraction failed.",
    )


def _normalized_bbox(
    rectangle: Any,
    geometry: _PageGeometry,
) -> tuple[float, float, float, float] | None:
    normalized = _bbox(_PYMUPDF.Rect(rectangle) * geometry.rotation_matrix)
    x0 = max(normalized[0], geometry.page_bbox[0])
    y0 = max(normalized[1], geometry.page_bbox[1])
    x1 = min(normalized[2], geometry.page_bbox[2])
    y1 = min(normalized[3], geometry.page_bbox[3])
    return (x0, y0, x1, y1) if x1 > x0 and y1 > y0 else None


def _bbox(rectangle: Any) -> tuple[float, float, float, float]:
    return (
        float(rectangle.x0),
        float(rectangle.y0),
        float(rectangle.x1),
        float(rectangle.y1),
    )


def _has_area(bbox: tuple[float, float, float, float]) -> bool:
    return bbox[2] > bbox[0] and bbox[3] > bbox[1]


def _combined_bbox(
    bboxes: Any,
) -> tuple[float, float, float, float]:
    values = tuple(bboxes)
    return (
        min(bbox[0] for bbox in values),
        min(bbox[1] for bbox in values),
        max(bbox[2] for bbox in values),
        max(bbox[3] for bbox in values),
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


def _normalize_inline_text(text: str) -> str:
    normalized = text.replace("\r", "").replace("\n", " ")
    has_leading_space = bool(normalized[:1].isspace())
    has_trailing_space = bool(normalized[-1:].isspace())
    content = " ".join(normalized.split())
    if not content:
        return ""
    return (
        (" " if has_leading_space else "")
        + content
        + (" " if has_trailing_space else "")
    )


def _normalize_block_text(text: str) -> str:
    return "\n".join(
        " ".join(line.split())
        for line in text.replace("\r", "").splitlines()
        if line.split()
    )


def _comparison_text(text: str) -> str:
    return "".join(text.split())


def _as_any(value: object) -> Any:
    return value


def _kind_order(kind: Literal["paragraph", "table_cell", "image"]) -> int:
    return {"paragraph": 0, "table_cell": 1, "image": 2}[kind]
