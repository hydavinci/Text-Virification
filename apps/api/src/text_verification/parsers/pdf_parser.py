from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

import pymupdf

from text_verification.compatibility.adapters import source_version_for_file
from text_verification.document_processing.pdf_classifier import classify_page
from text_verification.document_processing.pdf_models import (
    OcrRequirement,
    PdfCharacterMappingState,
    PdfDocumentMetadata,
    PdfExtractionWarning,
    PdfImage,
    PdfPageMetadata,
    PdfResourceLimits,
    PdfTable,
    PdfTableCell,
    PdfTextCharacter,
    PdfTextSpan,
    PdfWritingMode,
)
from text_verification.domain.documents import DocumentMetadata, DocumentModel, FileType, TextBlock
from text_verification.parsers.errors import ParserError, PdfResourceLimitError

_PARSER_NAME = "pymupdf-pdf"
_PARSER_VERSION = "3"
_PYMUPDF: Any = pymupdf
_MIN_VISUAL_GAP = 0.5
_FONT_GAP_RATIO = 0.08
_GLYPH_GAP_RATIO = 0.2
_RAWDICT_TEXT_FLAGS = pymupdf.TEXTFLAGS_RAWDICT & ~pymupdf.TEXT_PRESERVE_IMAGES


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
    all_spans = _extract_spans(raw_spans, [])
    tables, table_span_indices = _align_table_characters(
        tables,
        all_spans,
        limits=limits,
    )
    spans = [
        span
        for span in all_spans
        if span.span_index not in table_span_indices
    ]
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
    table_text_characters = 0
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
                text = _normalize_block_text(raw_text or "")
                if len(text) > limits.max_table_text_chars_per_cell:
                    raise PdfResourceLimitError(
                        limit="max_table_text_chars_per_cell",
                        maximum=limits.max_table_text_chars_per_cell,
                        actual=len(text),
                    )
                table_text_characters += len(text)
                if table_text_characters > limits.max_table_text_chars_per_page:
                    raise PdfResourceLimitError(
                        limit="max_table_text_chars_per_page",
                        maximum=limits.max_table_text_chars_per_page,
                        actual=table_text_characters,
                    )
                cells.append((text, raw_bbox))
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
    raw_line_index = 0
    for block in page.get_text("rawdict", flags=_RAWDICT_TEXT_FLAGS).get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            line_direction = _line_direction(line.get("dir"))
            writing_mode = _writing_mode(line.get("wmode"))
            for span_order, raw_span in enumerate(line.get("spans", [])):
                characters = _raw_span_characters(
                    raw_span,
                    geometry,
                    line_direction=line_direction,
                    writing_mode=writing_mode,
                    line_index=raw_line_index,
                    span_order=span_order,
                )
                if not characters:
                    continue
                bbox = _raw_span_bbox(raw_span, characters, geometry)
                raw_spans.append(
                    _RawSpan(
                        bbox=bbox,
                        raw=raw_span,
                        characters=characters,
                        line_direction=line_direction,
                        writing_mode=writing_mode,
                        line_index=raw_line_index,
                        span_order=span_order,
                    )
                )
            raw_line_index += 1
    return raw_spans


def _extract_spans(raw_spans: list[_RawSpan], tables: list[PdfTable]) -> list[PdfTextSpan]:
    del tables
    spans = [
        PdfTextSpan(
            text=raw_span.text,
            bbox=raw_span.bbox,
            font_name=str(raw_span.raw.get("font", "")) or "unknown",
            font_size=float(_as_any(raw_span.raw.get("size", 0.0))),
            font_flags=int(_as_any(raw_span.raw.get("flags", 0))),
            color=int(_as_any(raw_span.raw.get("color", 0))),
            span_index=index,
            characters=raw_span.characters,
            line_direction=raw_span.line_direction,
            writing_mode=raw_span.writing_mode,
            line_index=raw_span.line_index,
            span_order=raw_span.span_order,
        )
        for index, raw_span in enumerate(raw_spans)
    ]
    return _normalize_span_boundaries(spans)


def _align_table_characters(
    tables: list[PdfTable],
    spans: list[PdfTextSpan],
    *,
    limits: PdfResourceLimits,
) -> tuple[list[PdfTable], set[int]]:
    aligned_tables: list[PdfTable] = []
    used_span_indices: set[int] = set()
    for table in tables:
        aligned_rows: list[tuple[PdfTableCell, ...]] = []
        for row in table.rows:
            aligned_cells: list[PdfTableCell] = []
            for cell in row:
                if not cell.text or cell.bbox is None:
                    aligned_cells.append(cell)
                    continue
                candidates = _table_cell_candidate_spans(cell.bbox, spans)
                candidate_count = sum(
                    len(character.text)
                    for candidate in candidates
                    for character in candidate.characters
                )
                if candidate_count > limits.max_table_glyph_candidates_per_cell:
                    raise PdfResourceLimitError(
                        limit="max_table_glyph_candidates_per_cell",
                        maximum=limits.max_table_glyph_candidates_per_cell,
                        actual=candidate_count,
                    )
                used_span_indices.update(span.span_index for span in candidates)
                aligned_cells.append(
                    cell.model_copy(
                        update={
                            "characters": _align_cell_characters(
                                cell.text,
                                cell.bbox,
                                spans,
                                candidates=candidates,
                            )
                        }
                    )
                )
            aligned_rows.append(tuple(aligned_cells))
        aligned_tables.append(
            table.model_copy(update={"rows": tuple(aligned_rows)})
        )
    return aligned_tables, used_span_indices


def _align_cell_characters(
    text: str,
    bbox: tuple[float, float, float, float],
    spans: list[PdfTextSpan],
    *,
    candidates: list[PdfTextSpan] | None = None,
) -> tuple[PdfTextCharacter, ...]:
    resolved_candidates = (
        candidates
        if candidates is not None
        else _table_cell_candidate_spans(bbox, spans)
    )
    if not resolved_candidates:
        return _unmapped_character_models(text)
    lines = _visual_lines(tuple(resolved_candidates))
    _, _, candidate_groups = _lines_text_and_source_metadata(lines)
    target_units = _normalized_alignment_units(text)
    source_groups = [
        (candidate_group, units)
        for candidate_group in candidate_groups
        if isinstance(candidate_group.get("text"), str)
        and (units := _normalized_alignment_units(str(candidate_group["text"])))
    ]
    source_positions = _AlignmentTokenPositions.from_tokens(
        [units[0][0] for _, units in source_groups]
    )
    target_positions = _AlignmentTokenPositions.from_tokens(
        [unit[0] for unit in target_units]
    )
    mapped: dict[int, PdfTextCharacter] = {}
    source_index = 0
    target_index = 0
    while source_index < len(source_groups) and target_index < len(target_units):
        candidate_group, candidate_units = source_groups[source_index]
        candidate_token = candidate_units[0][0]
        target_token = target_units[target_index][0]
        if _alignment_tokens_match(candidate_token, target_token):
            if (
                target_index + len(candidate_units) <= len(target_units)
                and all(
                    _alignment_tokens_match(
                        candidate_units[unit_index][0],
                        target_units[target_index + unit_index][0],
                    )
                    for unit_index in range(1, len(candidate_units))
                )
            ):
                target_start = target_units[target_index][1]
                target_end = target_units[target_index + len(candidate_units) - 1][2]
                aligned_character = _aligned_table_character(
                    text=text[target_start:target_end],
                    source_start=target_start,
                    source_end=target_end,
                    source_group=candidate_group,
                )
                if aligned_character is not None:
                    mapped[target_start] = aligned_character
                target_index += len(candidate_units)
            source_index += 1
            continue

        next_source = source_positions.next_after(target_token, source_index + 1)
        next_target = target_positions.next_after(candidate_token, target_index + 1)
        if next_source is not None and (
            next_target is None
            or next_source - source_index <= next_target - target_index
        ):
            source_index = next_source
        elif next_target is not None:
            target_index = next_target
        else:
            source_index += 1
    aligned: list[PdfTextCharacter] = []
    cursor = 0
    while cursor < len(text):
        mapped_group = mapped.get(cursor)
        if mapped_group is not None:
            aligned.append(mapped_group)
            cursor = mapped_group.source_end
            continue
        character = text[cursor]
        mapping_state = (
            PdfCharacterMappingState.SYNTHETIC_SPACE
            if character.isspace()
            else PdfCharacterMappingState.UNMAPPED
        )
        aligned.append(
            PdfTextCharacter(
                text=character,
                bbox=None,
                source_start=cursor,
                source_end=cursor + 1,
                mapping_state=mapping_state,
                group_id=f"cell-unaligned-{cursor}",
            )
        )
        cursor += 1
    return tuple(aligned)


def _table_cell_candidate_spans(
    bbox: tuple[float, float, float, float],
    spans: list[PdfTextSpan],
) -> list[PdfTextSpan]:
    return [
        span
        for span in spans
        if (
            bbox[0] <= (span.bbox[0] + span.bbox[2]) / 2 <= bbox[2]
            and bbox[1] <= (span.bbox[1] + span.bbox[3]) / 2 <= bbox[3]
        )
    ]


def _normalized_alignment_units(text: str) -> list[tuple[str, int, int]]:
    units: list[tuple[str, int, int]] = []
    cursor = 0
    while cursor < len(text):
        start = cursor
        character = text[cursor]
        if character.isspace():
            cursor += 1
            while cursor < len(text) and text[cursor].isspace():
                cursor += 1
            units.append((" ", start, cursor))
            continue
        units.append((character, start, start + 1))
        cursor += 1
    return units


@dataclass
class _AlignmentTokenPositions:
    positions: dict[str, list[int]]
    cursors: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_tokens(cls, tokens: list[str]) -> _AlignmentTokenPositions:
        positions: dict[str, list[int]] = {}
        for index, token in enumerate(tokens):
            positions.setdefault(token, []).append(index)
        return cls(positions)

    def next_after(self, token: str, index: int) -> int | None:
        positions = self.positions.get(token)
        if positions is None:
            return None
        cursor = self.cursors.get(token, 0)
        while cursor < len(positions) and positions[cursor] < index:
            cursor += 1
        self.cursors[token] = cursor
        return positions[cursor] if cursor < len(positions) else None


def _alignment_tokens_match(source: str, target: str) -> bool:
    return source == target


def _aligned_table_character(
    *,
    text: str,
    source_start: int,
    source_end: int,
    source_group: dict[str, object],
) -> PdfTextCharacter | None:
    mapping_state_value = source_group.get("mapping_state")
    group_id = source_group.get("group_id")
    direction = _source_group_direction(source_group.get("line_direction"))
    writing_mode = source_group.get("writing_mode")
    raw_line_index = source_group.get("raw_line_index")
    span_order = source_group.get("span_order")
    if (
        not isinstance(mapping_state_value, str)
        or not isinstance(group_id, str)
        or not group_id
        or direction is None
        or isinstance(writing_mode, bool)
        or not isinstance(writing_mode, int)
        or writing_mode not in {mode.value for mode in PdfWritingMode}
        or isinstance(raw_line_index, bool)
        or not isinstance(raw_line_index, int)
        or raw_line_index < 0
        or (
            span_order is not None
            and (
                isinstance(span_order, bool)
                or not isinstance(span_order, int)
                or span_order < 0
            )
        )
    ):
        return None
    try:
        mapping_state = PdfCharacterMappingState(mapping_state_value)
    except ValueError:
        return None
    bbox = _source_group_bbox(source_group.get("bbox"))
    if mapping_state is PdfCharacterMappingState.GLYPH and (
        bbox is None or text.isspace() or span_order is None
    ):
        return None
    if (
        mapping_state is PdfCharacterMappingState.GLYPHLESS
        and (bbox is not None or text.isspace())
    ):
        return None
    if mapping_state is PdfCharacterMappingState.SYNTHETIC_SPACE and (
        bbox is not None or not text.isspace()
    ):
        return None
    if mapping_state is PdfCharacterMappingState.UNMAPPED:
        return None
    return PdfTextCharacter(
        text=text,
        bbox=bbox,
        source_start=source_start,
        source_end=source_end,
        mapping_state=mapping_state,
        group_id=group_id,
        line_direction=direction,
        writing_mode=PdfWritingMode(writing_mode),
        raw_line_index=raw_line_index,
        span_order=span_order,
    )


def _source_group_direction(
    value: object,
) -> tuple[float, float] | None:
    if not isinstance(value, tuple | list) or len(value) != 2:
        return None
    x, y = value
    if (
        isinstance(x, bool)
        or not isinstance(x, int | float)
        or not isfinite(float(x))
        or isinstance(y, bool)
        or not isinstance(y, int | float)
        or not isfinite(float(y))
        or (float(x) == 0.0 and float(y) == 0.0)
    ):
        return None
    return float(x), float(y)


def _source_group_bbox(
    value: object,
) -> tuple[float, float, float, float] | None:
    if value is None:
        return None
    if not isinstance(value, tuple | list) or len(value) != 4:
        return None
    coordinates: list[float] = []
    for coordinate in value:
        if (
            isinstance(coordinate, bool)
            or not isinstance(coordinate, int | float)
            or not isfinite(float(coordinate))
        ):
            return None
        coordinates.append(float(coordinate))
    x0, y0, x1, y1 = coordinates
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


def _unmapped_character_models(text: str) -> tuple[PdfTextCharacter, ...]:
    return tuple(
        PdfTextCharacter(
            text=character,
            bbox=None,
            source_start=source_start,
            source_end=source_start + 1,
            mapping_state=(
                PdfCharacterMappingState.SYNTHETIC_SPACE
                if character.isspace()
                else PdfCharacterMappingState.UNMAPPED
            ),
            group_id=f"cell-unaligned-{source_start}",
        )
        for source_start, character in enumerate(text)
    )


def _line_direction(value: object) -> tuple[float, float]:
    if isinstance(value, tuple | list) and len(value) == 2:
        x, y = value
        if (
            isinstance(x, int | float)
            and not isinstance(x, bool)
            and isinstance(y, int | float)
            and not isinstance(y, bool)
            and (float(x) != 0.0 or float(y) != 0.0)
        ):
            return float(x), float(y)
    return 1.0, 0.0


def _writing_mode(value: object) -> PdfWritingMode:
    return (
        PdfWritingMode.VERTICAL
        if value == PdfWritingMode.VERTICAL.value
        else PdfWritingMode.HORIZONTAL
    )


def _raw_span_bbox(
    raw_span: dict[str, object],
    characters: tuple[PdfTextCharacter, ...],
    geometry: _PageGeometry,
) -> tuple[float, float, float, float]:
    raw_bbox = raw_span.get("bbox")
    if raw_bbox is not None:
        normalized = _normalized_bbox(raw_bbox, geometry)
        if normalized is not None:
            return normalized
    mapped_bboxes = [
        character.bbox
        for character in characters
        if character.bbox is not None
    ]
    if mapped_bboxes:
        return _combined_bbox(mapped_bboxes)
    return geometry.page_bbox


def _raw_span_characters(
    raw_span: dict[str, object],
    geometry: _PageGeometry,
    *,
    line_direction: tuple[float, float],
    writing_mode: PdfWritingMode,
    line_index: int,
    span_order: int,
) -> tuple[PdfTextCharacter, ...]:
    normalized: list[
        tuple[
            str,
            tuple[float, float, float, float] | None,
            PdfCharacterMappingState,
            str,
        ]
    ] = []
    whitespace_pending = False
    raw_characters = raw_span.get("chars", [])
    if not isinstance(raw_characters, list):
        return ()
    for glyph_index, raw_character in enumerate(raw_characters):
        if not isinstance(raw_character, dict):
            continue
        raw_text = str(raw_character.get("c", ""))
        if not raw_text:
            continue
        group_id = f"line-{line_index}-span-{span_order}-glyph-{glyph_index}"
        if raw_text.isspace():
            if not whitespace_pending:
                normalized.append(
                    (
                        " ",
                        None,
                        PdfCharacterMappingState.SYNTHETIC_SPACE,
                        group_id,
                    )
                )
            whitespace_pending = True
            continue
        bbox_value = raw_character.get("bbox")
        bbox = (
            _normalized_bbox(bbox_value, geometry)
            if bbox_value is not None
            else None
        )
        mapping_state = (
            PdfCharacterMappingState.GLYPH
            if bbox is not None
            else PdfCharacterMappingState.GLYPHLESS
        )
        normalized.append((raw_text, bbox, mapping_state, group_id))
        whitespace_pending = False
    return _characters_with_offsets(
        normalized,
        line_direction=line_direction,
        writing_mode=writing_mode,
        raw_line_index=line_index,
        span_order=span_order,
    )


def _normalize_span_boundaries(spans: list[PdfTextSpan]) -> list[PdfTextSpan]:
    normalized: list[PdfTextSpan] = []
    for line in _visual_lines(tuple(spans)):
        normalized.extend(_normalize_line_span_boundaries(line.spans))
    return [
        span.model_copy(update={"span_index": span_index})
        for span_index, span in enumerate(normalized)
    ]


def _normalize_line_span_boundaries(
    spans: tuple[PdfTextSpan, ...],
) -> list[PdfTextSpan]:
    normalized: list[tuple[PdfTextSpan, list[PdfTextCharacter]]] = []
    pending_whitespace = False
    for span in spans:
        leading_whitespace, content, trailing_whitespace = _boundary_characters(
            span.characters
        )
        if not content:
            pending_whitespace = (
                pending_whitespace or leading_whitespace or trailing_whitespace
            )
            continue
        if not normalized:
            if pending_whitespace or leading_whitespace:
                content.insert(
                    0,
                    _synthetic_character(
                        f"line-{span.line_index}-span-{span.span_order}-leading-space"
                    ),
                )
        else:
            previous_span, previous_characters = normalized[-1]
            if (
                pending_whitespace
                or leading_whitespace
                or _has_visual_word_gap(
                    previous_span,
                    previous_characters,
                    span,
                    content,
                )
            ):
                previous_characters.append(
                    _synthetic_character(
                        f"line-{previous_span.line_index}-span-"
                        f"{previous_span.span_order}-boundary-{span.span_order}"
                    )
                )
        normalized.append((span, content))
        pending_whitespace = trailing_whitespace

    if normalized and pending_whitespace:
        final_span = normalized[-1][0]
        normalized[-1][1].append(
            _synthetic_character(
                f"line-{final_span.line_index}-span-"
                f"{final_span.span_order}-trailing-space"
            )
        )

    return [
        _span_with_characters(span, characters)
        for span, characters in normalized
    ]


def _boundary_characters(
    characters: tuple[PdfTextCharacter, ...],
) -> tuple[bool, list[PdfTextCharacter], bool]:
    first = 0
    while first < len(characters) and characters[first].text.isspace():
        first += 1
    last = len(characters)
    while last > first and characters[last - 1].text.isspace():
        last -= 1
    return first > 0, list(characters[first:last]), last < len(characters)


def _has_visual_word_gap(
    previous_span: PdfTextSpan,
    previous_characters: list[PdfTextCharacter],
    next_span: PdfTextSpan,
    next_characters: list[PdfTextCharacter],
) -> bool:
    previous = next(
        (
            character
            for character in reversed(previous_characters)
            if character.bbox is not None
        ),
        None,
    )
    following = next(
        (character for character in next_characters if character.bbox is not None),
        None,
    )
    if previous is None or following is None:
        return False
    previous_bbox = previous.bbox
    following_bbox = following.bbox
    assert previous_bbox is not None
    assert following_bbox is not None
    direction = previous_span.line_direction
    if (
        next_span.line_direction != direction
        or next_span.writing_mode is not previous_span.writing_mode
    ):
        return False
    previous_interval = _projected_bbox_interval(previous_bbox, direction)
    following_interval = _projected_bbox_interval(following_bbox, direction)
    gap = following_interval[0] - previous_interval[1]
    if gap <= 0:
        return False
    glyph_width = min(
        previous_interval[1] - previous_interval[0],
        following_interval[1] - following_interval[0],
    )
    threshold = max(
        _MIN_VISUAL_GAP,
        min(previous_span.font_size, next_span.font_size) * _FONT_GAP_RATIO,
        glyph_width * _GLYPH_GAP_RATIO,
    )
    return gap >= threshold


def _projected_bbox_interval(
    bbox: tuple[float, float, float, float],
    direction: tuple[float, float],
) -> tuple[float, float]:
    x0, y0, x1, y1 = bbox
    dx, dy = direction
    magnitude = (dx * dx + dy * dy) ** 0.5
    normalized_x = dx / magnitude
    normalized_y = dy / magnitude
    projections = (
        x0 * normalized_x + y0 * normalized_y,
        x0 * normalized_x + y1 * normalized_y,
        x1 * normalized_x + y0 * normalized_y,
        x1 * normalized_x + y1 * normalized_y,
    )
    return min(projections), max(projections)


def _span_with_characters(
    span: PdfTextSpan,
    characters: list[PdfTextCharacter],
) -> PdfTextSpan:
    values = [
        (
            character.text,
            character.bbox,
            character.mapping_state,
            character.group_id or f"span-{span.span_index}-group-{index}",
        )
        for index, character in enumerate(characters)
    ]
    normalized_characters = _characters_with_offsets(
        values,
        line_direction=span.line_direction,
        writing_mode=span.writing_mode,
        raw_line_index=span.line_index,
        span_order=span.span_order,
    )
    return span.model_copy(
        update={
            "text": "".join(character.text for character in normalized_characters),
            "characters": normalized_characters,
        }
    )


def _synthetic_character(group_id: str = "synthetic-space") -> PdfTextCharacter:
    return PdfTextCharacter(
        text=" ",
        bbox=None,
        source_start=0,
        source_end=1,
        mapping_state=PdfCharacterMappingState.SYNTHETIC_SPACE,
        group_id=group_id,
    )


def _characters_with_offsets(
    values: list[
        tuple[
            str,
            tuple[float, float, float, float] | None,
            PdfCharacterMappingState,
            str,
        ]
    ],
    *,
    line_direction: tuple[float, float] = (1.0, 0.0),
    writing_mode: PdfWritingMode = PdfWritingMode.HORIZONTAL,
    raw_line_index: int = 0,
    span_order: int | None = None,
) -> tuple[PdfTextCharacter, ...]:
    characters: list[PdfTextCharacter] = []
    cursor = 0
    for text, bbox, mapping_state, group_id in values:
        characters.append(
            PdfTextCharacter(
                text=text,
                bbox=bbox,
                source_start=cursor,
                source_end=cursor + len(text),
                mapping_state=mapping_state,
                group_id=group_id,
                line_direction=line_direction,
                writing_mode=writing_mode,
                raw_line_index=raw_line_index,
                span_order=span_order,
            )
        )
        cursor += len(text)
    return tuple(characters)


def _canonical_blocks(pages: tuple[PdfPageMetadata, ...]) -> tuple[list[TextBlock], str]:
    ordered: list[_ExtractedBlock] = []
    for page in pages:
        visual_lines = _visual_lines(page.spans)
        extracted: list[_ExtractedBlock] = []
        if visual_lines and not page.tables and not page.images:
            extracted.append(_page_block(page.page, visual_lines))
        else:
            extracted.extend(_line_blocks(page.page, visual_lines))
        extracted.extend(_table_blocks(page.page, page.tables))
        extracted.extend(_image_blocks(page.page, page.images))
        ordered.extend(_order_page_blocks(extracted))
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
    line_index: int
    line_direction: tuple[float, float]
    writing_mode: PdfWritingMode

    @property
    def text(self) -> str:
        return "".join(span.text for span in self.spans)


@dataclass(frozen=True)
class _RawSpan:
    bbox: tuple[float, float, float, float]
    raw: dict[str, object]
    characters: tuple[PdfTextCharacter, ...]
    line_direction: tuple[float, float]
    writing_mode: PdfWritingMode
    line_index: int
    span_order: int

    @property
    def text(self) -> str:
        return "".join(character.text for character in self.characters)


@dataclass(frozen=True)
class _ExtractedPage:
    metadata: PdfPageMetadata
    warnings: tuple[PdfExtractionWarning, ...]


@dataclass(frozen=True)
class _PageGeometry:
    page_bbox: tuple[float, float, float, float]
    rotation_matrix: Any


def _visual_lines(spans: tuple[PdfTextSpan, ...]) -> list[_VisualLine]:
    grouped: dict[int, list[PdfTextSpan]] = {}
    for span in spans:
        grouped.setdefault(span.line_index, []).append(span)
    lines = [
        _VisualLine(
            spans=tuple(line),
            bbox=_combined_bbox(span.bbox for span in line),
            line_index=line[0].line_index,
            line_direction=line[0].line_direction,
            writing_mode=line[0].writing_mode,
        )
        for line in grouped.values()
    ]
    if any(_line_preserves_raw_flow(line) for line in lines):
        return lines
    return sorted(
        lines,
        key=lambda line: (
            line.bbox[1],
            line.bbox[0],
            line.line_index,
        ),
    )


def _line_preserves_raw_flow(line: _VisualLine) -> bool:
    return (
        line.writing_mode is PdfWritingMode.VERTICAL
        or line.line_direction[0] <= 0.0
        or line.line_direction[1] != 0.0
    )


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
    preserve_raw_flow: bool


def _order_page_blocks(items: list[_ExtractedBlock]) -> list[_ExtractedBlock]:
    directional = [item for item in items if item.preserve_raw_flow]
    if not directional:
        return sorted(items, key=_visual_block_order)
    remaining = [item for item in items if not item.preserve_raw_flow]
    return [
        *sorted(directional, key=lambda item: (item.ordinal, item.block_id)),
        *sorted(remaining, key=_visual_block_order),
    ]


def _visual_block_order(item: _ExtractedBlock) -> tuple[float, float, int, int]:
    return (
        item.bbox[1],
        item.bbox[0],
        _kind_order(item.kind),
        item.ordinal,
    )


def _page_block(page: int, lines: list[_VisualLine]) -> _ExtractedBlock:
    text, segments, characters = _lines_text_and_source_metadata(lines)
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
        source_locator={
            "locator_kind": "page",
            "page": page,
            "segments": segments,
            "characters": characters,
        },
        preserve_raw_flow=False,
    )


def _line_blocks(page: int, lines: list[_VisualLine]) -> list[_ExtractedBlock]:
    blocks: list[_ExtractedBlock] = []
    for line_index, line in enumerate(lines):
        segments, characters, _ = _line_source_metadata(
            line.spans,
            start=0,
            line_index=line_index,
        )
        blocks.append(
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
                    "segments": segments,
                    "characters": characters,
                },
                preserve_raw_flow=_line_preserves_raw_flow(line),
            )
        )
    return blocks


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
                "characters": _table_cell_source_characters(cell),
            },
            preserve_raw_flow=False,
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
            preserve_raw_flow=False,
        )
        for image in images
    ]


def _lines_text_and_source_metadata(
    lines: list[_VisualLine],
) -> tuple[str, list[dict[str, object]], list[dict[str, object]]]:
    text_parts: list[str] = []
    segments: list[dict[str, object]] = []
    characters: list[dict[str, object]] = []
    cursor = 0
    for line_index, line in enumerate(lines):
        if line_index:
            text_parts.append("\n")
            characters.append(
                _source_character(
                    text="\n",
                    bbox=None,
                    source_start=cursor,
                    mapping_state=PdfCharacterMappingState.SYNTHETIC_SPACE,
                    line_index=line_index - 1,
                    span_index=None,
                    group_id=f"line-{line.line_index}-separator-before",
                    line_direction=line.line_direction,
                    writing_mode=line.writing_mode,
                    raw_line_index=line.line_index,
                    span_order=None,
                )
            )
            cursor += 1
        line_text = line.text
        text_parts.append(line_text)
        line_segments, line_characters, cursor = _line_source_metadata(
            line.spans,
            start=cursor,
            line_index=line_index,
        )
        segments.extend(line_segments)
        characters.extend(line_characters)
    return "".join(text_parts), segments, characters


def _line_source_metadata(
    spans: tuple[PdfTextSpan, ...],
    *,
    start: int,
    line_index: int,
) -> tuple[list[dict[str, object]], list[dict[str, object]], int]:
    cursor = start
    segments: list[dict[str, object]] = []
    characters: list[dict[str, object]] = []
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
        characters.extend(
            _source_character(
                text=character.text,
                bbox=character.bbox,
                source_start=cursor + character.source_start,
                mapping_state=character.mapping_state,
                line_index=line_index,
                span_index=span.span_index,
                group_id=character.group_id,
                line_direction=span.line_direction,
                writing_mode=span.writing_mode,
                raw_line_index=span.line_index,
                span_order=span.span_order,
            )
            for character in span.characters
        )
        cursor = end
    return segments, characters, cursor


def _line_segments_from_text(
    text: str,
    bbox: tuple[float, float, float, float],
) -> list[dict[str, object]]:
    return [{"start": 0, "end": len(text), "text": text, "bbox": list(bbox)}]


def _table_cell_source_characters(
    cell: PdfTableCell,
) -> list[dict[str, object]]:
    characters: list[dict[str, object]] = []
    for character in cell.characters:
        characters.append(
            _source_character(
                text=character.text,
                bbox=character.bbox,
                source_start=character.source_start,
                mapping_state=character.mapping_state,
                line_index=character.raw_line_index,
                span_index=None,
                group_id=character.group_id,
                line_direction=character.line_direction,
                writing_mode=character.writing_mode,
                raw_line_index=character.raw_line_index,
                span_order=character.span_order,
            )
        )
    return characters


def _source_character(
    *,
    text: str,
    bbox: tuple[float, float, float, float] | None,
    source_start: int,
    mapping_state: PdfCharacterMappingState,
    line_index: int,
    span_index: int | None,
    group_id: str | None,
    line_direction: tuple[float, float],
    writing_mode: PdfWritingMode,
    raw_line_index: int,
    span_order: int | None,
) -> dict[str, object]:
    return {
        "text": text,
        "bbox": list(bbox) if bbox is not None else None,
        "source_start": source_start,
        "source_end": source_start + len(text),
        "mapping_state": mapping_state.value,
        "line_index": line_index,
        "span_index": span_index,
        "group_id": group_id,
        "line_direction": list(line_direction),
        "writing_mode": writing_mode.value,
        "raw_line_index": raw_line_index,
        "span_order": span_order,
    }


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
