from __future__ import annotations

import base64
import binascii
import io
import math
import os
import stat
import struct
from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal, TypedDict
from uuid import uuid4

import pymupdf
from docx import Document
from docx.enum.section import WD_ORIENT
from docx.image.exceptions import (
    InvalidImageStreamError,
    UnexpectedEndOfFileError,
    UnrecognizedImageError,
)
from docx.oxml.ns import qn
from docx.shared import Inches, Pt

from text_verification.compatibility.exporters import ExportError
from text_verification.domain.documents import (
    DocumentModel,
    ExportFormat,
    TextBlock,
)

DOCX_RECONSTRUCTION = ExportFormat.DOCX_RECONSTRUCTION
_DEFAULT_PAGE_WIDTH_POINTS = 612.0
_DEFAULT_PAGE_HEIGHT_POINTS = 792.0
_DEFAULT_MARGIN_POINTS = 54.0
_FIXED_CORE_PROPERTY_TIME = datetime(2000, 1, 1, tzinfo=UTC)
_XML_REPLACEMENT_CHARACTER = "\ufffd"
_PYMUPDF: Any = pymupdf

type SupportedImageMime = Literal["image/png", "image/jpeg"]


class InMemoryImagePayload(TypedDict):
    kind: Literal["bytes"]
    mime_type: SupportedImageMime
    data: bytes


class Base64ImagePayload(TypedDict):
    kind: Literal["base64"]
    mime_type: SupportedImageMime
    data: str


class RepositoryImagePayload(TypedDict):
    kind: Literal["repository_path"]
    mime_type: SupportedImageMime
    path: str


class PdfXrefImagePayload(TypedDict):
    kind: Literal["pdf_xref"]
    path: str
    xref: int


type DocxImagePayload = (
    InMemoryImagePayload
    | Base64ImagePayload
    | RepositoryImagePayload
    | PdfXrefImagePayload
)


@dataclass(frozen=True)
class DocxReconstructionLimits:
    max_output_elements: int = 20_000
    max_tables: int = 100
    max_table_index: int = 10_000
    max_table_rows: int = 1_000
    max_table_columns: int = 100
    max_table_cells: int = 10_000
    max_image_bytes: int = 20 * 1024 * 1024
    max_pdf_source_bytes: int = 200 * 1024 * 1024
    max_image_width: int = 20_000
    max_image_height: int = 20_000
    max_image_pixels: int = 40_000_000
    max_output_bytes: int = 100 * 1024 * 1024

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{field.name} must be a positive integer")


@dataclass(frozen=True)
class _Image:
    content: bytes
    mime_type: SupportedImageMime
    width: int
    height: int


@dataclass(frozen=True)
class _Table:
    page: int | None
    table_index: int
    rows: int
    columns: int
    cells: dict[tuple[int, int], TextBlock]
    merges: dict[tuple[int, int], tuple[int, int]]
    merged_coordinates: frozenset[tuple[int, int]]
    first_source_index: int
    y: float
    x: float


type _RenderUnit = TextBlock | _Table


@dataclass(frozen=True)
class DocxReconstructionExporter:
    limits: DocxReconstructionLimits = DocxReconstructionLimits()
    repository_root: Path | None = None
    file_type: ExportFormat = DOCX_RECONSTRUCTION

    def export(self, document: DocumentModel, target: Path) -> Path:
        output = Document()
        _set_core_properties(output, document)
        _set_page_setup(output, document)

        units = _render_units(document, self.limits)
        for unit in units:
            if isinstance(unit, _Table):
                _add_table(output, unit)
            elif unit.kind == "image":
                _add_image(
                    output,
                    _image_from_block(unit, self.limits, self.repository_root),
                )
            elif unit.kind in {"heading", "paragraph"}:
                _add_text_block(output, unit)

        stream = io.BytesIO()
        output.save(stream)
        content = stream.getvalue()
        if len(content) > self.limits.max_output_bytes:
            raise ExportError("Reconstructed DOCX exceeds the configured output size limit.")
        _publish_atomic(target, content)
        return target


def _render_units(
    document: DocumentModel,
    limits: DocxReconstructionLimits,
) -> list[_RenderUnit]:
    table_groups: dict[tuple[int | None, int], list[tuple[int, TextBlock]]] = {}
    non_table: list[tuple[int, TextBlock]] = []
    for source_index, block in enumerate(document.blocks):
        if block.kind == "table_cell":
            if block.table_index is None:
                raise ExportError("Table cells require a table index.")
            if (
                isinstance(block.table_index, bool)
                or block.table_index < 0
                or block.table_index >= limits.max_table_index
            ):
                raise ExportError("Table index is outside configured limits.")
            table_groups.setdefault((block.page, block.table_index), []).append(
                (source_index, block)
            )
        elif block.kind in {"heading", "paragraph", "image"}:
            non_table.append((source_index, block))

    if len(table_groups) > limits.max_tables:
        raise ExportError("Document exceeds the configured table limit.")

    tables = [
        _table_from_blocks(document, key, blocks, limits)
        for key, blocks in table_groups.items()
    ]
    if len(non_table) + sum(table.rows * table.columns for table in tables) > (
        limits.max_output_elements
    ):
        raise ExportError("Document exceeds the configured output element limit.")

    indexed_units: list[tuple[tuple[float, ...], _RenderUnit]] = []
    indexed_units.extend(
        (_block_order(block, source_index), block)
        for source_index, block in non_table
    )
    indexed_units.extend((_table_order(table), table) for table in tables)
    indexed_units.sort(key=lambda item: item[0])
    return [unit for _, unit in indexed_units]


def _table_from_blocks(
    document: DocumentModel,
    key: tuple[int | None, int],
    indexed_blocks: list[tuple[int, TextBlock]],
    limits: DocxReconstructionLimits,
) -> _Table:
    page, table_index = key
    cells: dict[tuple[int, int], TextBlock] = {}
    declared_shapes: set[tuple[int, int]] = set()
    for _, block in indexed_blocks:
        if (
            block.row_index is None
            or block.cell_index is None
            or isinstance(block.row_index, bool)
            or isinstance(block.cell_index, bool)
        ):
            raise ExportError("Table cells require row and cell indices.")
        if (
            block.row_index < 0
            or block.cell_index < 0
            or block.row_index >= limits.max_table_rows
            or block.cell_index >= limits.max_table_columns
        ):
            raise ExportError("Table dimensions or cell coordinates exceed configured limits.")
        coordinate = (block.row_index, block.cell_index)
        if coordinate in cells:
            raise ExportError("Table contains duplicate cell coordinates.")
        cells[coordinate] = block
        shape = _declared_table_shape(block)
        if shape is not None:
            declared_shapes.add(shape)

    pdf_shape = _pdf_table_shape(document, page, table_index)
    if pdf_shape is not None:
        declared_shapes.add(pdf_shape)
    if len(declared_shapes) > 1:
        raise ExportError("Table metadata contains conflicting dimensions.")

    derived_rows = max(row for row, _ in cells) + 1
    derived_columns = max(column for _, column in cells) + 1
    rows, columns = next(iter(declared_shapes), (derived_rows, derived_columns))
    if rows < derived_rows or columns < derived_columns:
        raise ExportError("Table cell coordinates exceed declared dimensions.")
    if rows > limits.max_table_rows or columns > limits.max_table_columns:
        raise ExportError("Table dimensions exceed configured limits.")
    if rows * columns > limits.max_table_cells:
        raise ExportError("Table cell count exceeds the configured limit.")
    if not declared_shapes and len(cells) != rows * columns:
        raise ExportError("Table cells do not form a rectangular shape.")

    merges, merged_coordinates = _table_merges(cells, rows, columns)
    first_source_index = min(index for index, _ in indexed_blocks)
    bboxes = [block.bbox for _, block in indexed_blocks if block.bbox is not None]
    return _Table(
        page=page,
        table_index=table_index,
        rows=rows,
        columns=columns,
        cells=cells,
        merges=merges,
        merged_coordinates=frozenset(merged_coordinates),
        first_source_index=first_source_index,
        y=min((bbox[1] for bbox in bboxes), default=math.inf),
        x=min((bbox[0] for bbox in bboxes), default=math.inf),
    )


def _declared_table_shape(block: TextBlock) -> tuple[int, int] | None:
    declared: list[tuple[int, int]] = []
    raw_shape = block.source_locator.get("table_shape")
    if raw_shape is not None:
        if not isinstance(raw_shape, Mapping) or set(raw_shape) != {"rows", "columns"}:
            raise ExportError("Table shape metadata is invalid.")
        declared.append(
            _validated_table_shape(raw_shape.get("rows"), raw_shape.get("columns"))
        )
    row_count = block.source_locator.get("row_count")
    column_count = block.source_locator.get("column_count")
    if row_count is not None or column_count is not None:
        declared.append(_validated_table_shape(row_count, column_count))
    if len(set(declared)) > 1:
        raise ExportError("Table metadata contains conflicting dimensions.")
    return declared[0] if declared else None


def _validated_table_shape(rows: object, columns: object) -> tuple[int, int]:
    if (
        isinstance(rows, bool)
        or not isinstance(rows, int)
        or isinstance(columns, bool)
        or not isinstance(columns, int)
        or rows <= 0
        or columns <= 0
    ):
        raise ExportError("Table shape metadata is invalid.")
    return rows, columns


def _table_merges(
    cells: Mapping[tuple[int, int], TextBlock],
    rows: int,
    columns: int,
) -> tuple[dict[tuple[int, int], tuple[int, int]], set[tuple[int, int]]]:
    merges: dict[tuple[int, int], tuple[int, int]] = {}
    occupied: set[tuple[int, int]] = set()
    merged_coordinates: set[tuple[int, int]] = set()
    for coordinate, block in sorted(cells.items()):
        raw_merge = block.source_locator.get("merge")
        if raw_merge is None:
            continue
        if (
            not isinstance(raw_merge, Mapping)
            or set(raw_merge) != {"row_span", "column_span"}
        ):
            raise ExportError("Table merge metadata is invalid.")
        row_span = raw_merge.get("row_span")
        column_span = raw_merge.get("column_span")
        if (
            isinstance(row_span, bool)
            or not isinstance(row_span, int)
            or isinstance(column_span, bool)
            or not isinstance(column_span, int)
            or row_span <= 0
            or column_span <= 0
        ):
            raise ExportError("Table merge metadata is invalid.")
        row_index, column_index = coordinate
        if row_index + row_span > rows or column_index + column_span > columns:
            raise ExportError("Table merge exceeds declared dimensions.")
        covered = {
            (row, column)
            for row in range(row_index, row_index + row_span)
            for column in range(column_index, column_index + column_span)
        }
        if occupied.intersection(covered):
            raise ExportError("Table merge regions overlap.")
        for covered_coordinate in covered - {coordinate}:
            covered_block = cells.get(covered_coordinate)
            if covered_block is not None and (
                covered_block.text
                or covered_block.source_locator.get("merge") is not None
            ):
                raise ExportError("Merged table cells contain conflicting content.")
        occupied.update(covered)
        merged_coordinates.update(covered - {coordinate})
        if row_span > 1 or column_span > 1:
            merges[coordinate] = (row_span, column_span)
    return merges, merged_coordinates


def _pdf_table_shape(
    document: DocumentModel,
    page: int | None,
    table_index: int,
) -> tuple[int, int] | None:
    if document.metadata.pdf is None or page is None:
        return None
    if not 1 <= page <= len(document.metadata.pdf.pages):
        return None
    page_metadata = document.metadata.pdf.pages[page - 1]
    for table in page_metadata.tables:
        if table.table_index == table_index:
            return table.row_count, table.column_count
    return None


def _block_order(block: TextBlock, source_index: int) -> tuple[float, ...]:
    page = float(block.page) if block.page is not None else math.inf
    if block.bbox is None:
        return page, math.inf, math.inf, float(source_index), 0.0
    return page, block.bbox[1], block.bbox[0], float(source_index), 0.0


def _table_order(table: _Table) -> tuple[float, ...]:
    page = float(table.page) if table.page is not None else math.inf
    return page, table.y, table.x, float(table.first_source_index), 1.0


def _add_text_block(document: Any, block: TextBlock) -> None:
    if block.kind == "heading":
        level = _heading_level(block.style.get("level"))
        paragraph = document.add_paragraph(style=f"Heading {level}")
    else:
        paragraph = document.add_paragraph()
    run = paragraph.add_run()
    _set_run_text(run, block.text)
    _apply_run_style(run, block.style)


def _heading_level(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 1
    return min(9, max(1, value))


def _set_run_text(run: Any, text: str) -> None:
    lines = _xml_safe_text(text).split("\n")
    run.add_text(lines[0])
    for line in lines[1:]:
        run.add_break()
        run.add_text(line)


def _apply_run_style(run: Any, style: Mapping[str, object]) -> None:
    raw_font = style.get("font")
    font = raw_font if isinstance(raw_font, Mapping) else {}
    name = style.get(
        "east_asia_font",
        font.get("east_asia", font.get("eastAsia", font.get("name", font.get("family")))),
    )
    if isinstance(name, str) and name:
        run.font.name = name
        run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), name)

    size = style.get("estimated_font_size", style.get("font_size", font.get("size")))
    if (
        isinstance(size, int | float)
        and not isinstance(size, bool)
        and math.isfinite(float(size))
        and 1.0 <= float(size) <= 200.0
    ):
        run.font.size = Pt(float(size))

    bold = font.get("bold")
    italic = font.get("italic")
    flags = font.get("flags")
    if isinstance(bold, bool):
        run.bold = bold
    elif isinstance(flags, int) and not isinstance(flags, bool):
        run.bold = bool(flags & 16)
    if isinstance(italic, bool):
        run.italic = italic
    elif isinstance(flags, int) and not isinstance(flags, bool):
        run.italic = bool(flags & 2)


def _add_table(document: Any, source: _Table) -> None:
    table = document.add_table(rows=source.rows, cols=source.columns)
    for (row_index, column_index), (row_span, column_span) in sorted(
        source.merges.items()
    ):
        table.cell(row_index, column_index).merge(
            table.cell(
                row_index + row_span - 1,
                column_index + column_span - 1,
            )
        )
    for (row_index, column_index), block in sorted(source.cells.items()):
        if (row_index, column_index) in source.merged_coordinates:
            continue
        cell = table.cell(row_index, column_index)
        if (row_index, column_index) in source.merges:
            cell.text = ""
        paragraph = cell.paragraphs[0]
        run = paragraph.add_run()
        _set_run_text(run, block.text)
        _apply_run_style(run, block.style)


def _add_image(document: Any, image: _Image) -> None:
    section = document.sections[-1]
    content_width = section.page_width - section.left_margin - section.right_margin
    natural_width = Inches(image.width / 96.0)
    width = min(natural_width, content_width)
    try:
        document.add_picture(io.BytesIO(image.content), width=width)
    except (
        InvalidImageStreamError,
        UnexpectedEndOfFileError,
        UnrecognizedImageError,
    ) as error:
        raise ExportError("Image payload is malformed or unsupported.") from error


def _image_from_block(
    block: TextBlock,
    limits: DocxReconstructionLimits,
    repository_root: Path | None,
) -> _Image:
    raw = block.source_locator.get("image_payload")
    if not isinstance(raw, Mapping):
        raise ExportError("Image block is missing its image payload.")
    kind = raw.get("kind")
    if kind == "bytes":
        _validate_payload_keys(raw, {"kind", "mime_type", "data"})
        mime_type = _declared_image_mime(raw.get("mime_type"))
        data = raw.get("data")
        if not isinstance(data, bytes):
            raise ExportError("Image byte payload must use in-memory bytes.")
        content = data
    elif kind == "base64":
        _validate_payload_keys(raw, {"kind", "mime_type", "data"})
        mime_type = _declared_image_mime(raw.get("mime_type"))
        data = raw.get("data")
        if not isinstance(data, str):
            raise ExportError("Image base64 payload must use text data.")
        try:
            content = base64.b64decode(data, validate=True)
        except (ValueError, binascii.Error) as error:
            raise ExportError("Image payload contains invalid base64 data.") from error
    elif kind == "repository_path":
        _validate_payload_keys(raw, {"kind", "mime_type", "path"})
        mime_type = _declared_image_mime(raw.get("mime_type"))
        content = _read_repository_file(
            repository_root,
            raw.get("path"),
            max_bytes=limits.max_image_bytes,
        )
    elif kind == "pdf_xref":
        _validate_payload_keys(raw, {"kind", "path", "xref"})
        content, mime_type = _extract_pdf_image(
            repository_root,
            raw.get("path"),
            raw.get("xref"),
            limits,
        )
    else:
        raise ExportError("Image payload contract is invalid.")
    if not content or len(content) > limits.max_image_bytes:
        raise ExportError("Image payload exceeds the configured size limit.")
    width, height, detected_mime = _image_dimensions(content)
    if detected_mime != mime_type:
        raise ExportError("Image payload MIME type does not match its signature.")
    if (
        width > limits.max_image_width
        or height > limits.max_image_height
        or width * height > limits.max_image_pixels
    ):
        raise ExportError("Image dimensions exceed configured limits.")
    return _Image(content, detected_mime, width, height)


def _validate_payload_keys(raw: Mapping[object, object], expected: set[str]) -> None:
    if set(raw) != expected:
        raise ExportError("Image payload contract is invalid.")


def _declared_image_mime(value: object) -> SupportedImageMime:
    if value == "image/png":
        return "image/png"
    if value == "image/jpeg":
        return "image/jpeg"
    raise ExportError("Image payload has an unsupported MIME type.")


def _extract_pdf_image(
    repository_root: Path | None,
    raw_path: object,
    raw_xref: object,
    limits: DocxReconstructionLimits,
) -> tuple[bytes, SupportedImageMime]:
    if isinstance(raw_xref, bool) or not isinstance(raw_xref, int) or raw_xref <= 0:
        raise ExportError("PDF image payload has an invalid image reference.")
    source = _read_repository_file(
        repository_root,
        raw_path,
        max_bytes=limits.max_pdf_source_bytes,
    )
    try:
        pdf: Any = _PYMUPDF.open(stream=source, filetype="pdf")
    except (RuntimeError, ValueError) as error:
        raise ExportError("Repository PDF image source is invalid.") from error
    try:
        extracted = pdf.extract_image(raw_xref)
    except (RuntimeError, ValueError) as error:
        raise ExportError("PDF image reference could not be extracted.") from error
    finally:
        pdf.close()
    content = extracted.get("image")
    extension = extracted.get("ext")
    if not isinstance(content, bytes):
        raise ExportError("PDF image reference did not contain image data.")
    if extension in {"jpg", "jpeg"}:
        return content, "image/jpeg"
    if extension == "png":
        return content, "image/png"
    raise ExportError("PDF image reference uses an unsupported format.")


def _read_repository_file(
    repository_root: Path | None,
    raw_path: object,
    *,
    max_bytes: int,
) -> bytes:
    if repository_root is None:
        raise ExportError("Image repository is not configured.")
    relative_path = _validated_repository_path(raw_path)
    root_fd = _open_absolute_directory(repository_root, "Image repository is unsafe.")
    directory_fd = root_fd
    opened_directories: list[int] = []
    file_fd = -1
    try:
        for part in relative_path.parts[:-1]:
            next_fd = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=directory_fd,
            )
            opened_directories.append(next_fd)
            directory_fd = next_fd
        file_fd = os.open(
            relative_path.name,
            os.O_RDONLY | os.O_NOFOLLOW,
            dir_fd=directory_fd,
        )
        file_stat = os.fstat(file_fd)
        if not stat.S_ISREG(file_stat.st_mode):
            raise ExportError("Image repository path must name a regular file.")
        if file_stat.st_size <= 0 or file_stat.st_size > max_bytes:
            raise ExportError("Image repository file exceeds the configured size limit.")
        content = _read_bounded(file_fd, max_bytes)
        if len(content) != file_stat.st_size:
            raise ExportError("Image repository file changed while it was read.")
        return content
    except ExportError:
        raise
    except OSError as error:
        raise ExportError("Image repository path is unsafe or missing.") from error
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        for opened_fd in reversed(opened_directories):
            os.close(opened_fd)
        os.close(root_fd)


def _validated_repository_path(value: object) -> PurePosixPath:
    if (
        not isinstance(value, str)
        or not value
        or "\x00" in value
        or "\\" in value
        or value.startswith("/")
        or (len(value) >= 2 and value[1] == ":")
    ):
        raise ExportError("Image repository path is unsafe.")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ExportError("Image repository path is unsafe.")
    return PurePosixPath(*parts)


def _read_bounded(file_fd: int, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    remaining = max_bytes + 1
    while remaining > 0:
        chunk = os.read(file_fd, min(1024 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    content = b"".join(chunks)
    if len(content) > max_bytes:
        raise ExportError("Image repository file exceeds the configured size limit.")
    return content


def _image_dimensions(
    content: bytes,
) -> tuple[int, int, SupportedImageMime]:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        if len(content) < 24 or content[12:16] != b"IHDR":
            raise ExportError("PNG image payload is malformed.")
        width, height = struct.unpack(">II", content[16:24])
        if width <= 0 or height <= 0:
            raise ExportError("PNG image dimensions are invalid.")
        return width, height, "image/png"
    if content.startswith(b"\xff\xd8") and content.endswith(b"\xff\xd9"):
        width, height = _jpeg_dimensions(content)
        return width, height, "image/jpeg"
    raise ExportError("Image payload signature is unsupported.")


def _jpeg_dimensions(content: bytes) -> tuple[int, int]:
    offset = 2
    while offset + 4 <= len(content):
        if content[offset] != 0xFF:
            raise ExportError("JPEG image payload is malformed.")
        while offset < len(content) and content[offset] == 0xFF:
            offset += 1
        if offset >= len(content):
            break
        marker = content[offset]
        offset += 1
        if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        if offset + 2 > len(content):
            break
        segment_length = int.from_bytes(content[offset : offset + 2], "big")
        if segment_length < 2 or offset + segment_length > len(content):
            raise ExportError("JPEG image payload is malformed.")
        if marker in {
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        }:
            if segment_length < 7:
                raise ExportError("JPEG image payload is malformed.")
            height = int.from_bytes(content[offset + 3 : offset + 5], "big")
            width = int.from_bytes(content[offset + 5 : offset + 7], "big")
            if width <= 0 or height <= 0:
                raise ExportError("JPEG image dimensions are invalid.")
            return width, height
        offset += segment_length
    raise ExportError("JPEG image dimensions are missing.")


def _set_core_properties(output: Any, document: DocumentModel) -> None:
    output.core_properties.title = _xml_safe_text(Path(document.source_name).stem)
    output.core_properties.created = _FIXED_CORE_PROPERTY_TIME
    output.core_properties.modified = _FIXED_CORE_PROPERTY_TIME


def _xml_safe_text(value: str) -> str:
    normalized: list[str] = []
    for character in value:
        codepoint = ord(character)
        if (
            character in {"\t", "\n", "\r"}
            or 0x20 <= codepoint <= 0x7E
            or 0xA0 <= codepoint <= 0xD7FF
            or 0xE000 <= codepoint <= 0xFFFD
            or 0x10000 <= codepoint <= 0x10FFFF
        ):
            normalized.append(character)
        else:
            normalized.append(_XML_REPLACEMENT_CHARACTER)
    return "".join(normalized)


def _set_page_setup(output: Any, document: DocumentModel) -> None:
    width = _DEFAULT_PAGE_WIDTH_POINTS
    height = _DEFAULT_PAGE_HEIGHT_POINTS
    if document.metadata.pdf is not None and document.metadata.pdf.pages:
        page_bbox = document.metadata.pdf.pages[0].page_bbox
        candidate_width = page_bbox[2] - page_bbox[0]
        candidate_height = page_bbox[3] - page_bbox[1]
        if 72.0 <= candidate_width <= 2_000.0 and 72.0 <= candidate_height <= 2_000.0:
            width = candidate_width
            height = candidate_height
    section = output.sections[0]
    section.page_width = Pt(width)
    section.page_height = Pt(height)
    section.orientation = WD_ORIENT.LANDSCAPE if width > height else WD_ORIENT.PORTRAIT
    section.top_margin = Pt(_DEFAULT_MARGIN_POINTS)
    section.right_margin = Pt(_DEFAULT_MARGIN_POINTS)
    section.bottom_margin = Pt(_DEFAULT_MARGIN_POINTS)
    section.left_margin = Pt(_DEFAULT_MARGIN_POINTS)


def _publish_atomic(target: Path, content: bytes) -> None:
    if not target.is_absolute() or target.name in {"", ".", ".."} or "\x00" in target.name:
        raise ExportError("Target path must be an absolute DOCX path.")
    if target.suffix.lower() != ".docx":
        raise ExportError("Target path must use the .docx extension.")
    parent_fd = _open_absolute_directory(
        target.parent,
        "Target parent directory is unsafe or missing.",
    )
    temp_name = f".{target.name}.{uuid4().hex}.uploading"
    temp_fd = -1
    target_fd = -1
    linked = False
    inode: tuple[int, int] | None = None
    try:
        temp_fd = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent_fd,
        )
        _write_all(temp_fd, content)
        os.fsync(temp_fd)
        temp_stat = os.fstat(temp_fd)
        inode = temp_stat.st_dev, temp_stat.st_ino
        try:
            os.link(
                temp_name,
                target.name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
            linked = True
        except FileExistsError as error:
            raise ExportError("Target already exists and was not overwritten.") from error
        target_fd = os.open(
            target.name,
            os.O_RDONLY | os.O_NOFOLLOW,
            dir_fd=parent_fd,
        )
        target_stat = os.fstat(target_fd)
        if (target_stat.st_dev, target_stat.st_ino) != inode:
            raise ExportError("Published target does not match the reconstructed document.")
        os.unlink(temp_name, dir_fd=parent_fd)
        temp_name = ""
        os.fsync(parent_fd)
    except ExportError:
        if linked and inode is not None:
            _unlink_if_inode(parent_fd, target.name, inode)
        raise
    except OSError as error:
        if linked and inode is not None:
            _unlink_if_inode(parent_fd, target.name, inode)
        raise ExportError("Reconstructed DOCX could not be published safely.") from error
    finally:
        if target_fd >= 0:
            os.close(target_fd)
        if temp_fd >= 0:
            os.close(temp_fd)
        if temp_name:
            try:
                os.unlink(temp_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
        os.close(parent_fd)


def _open_absolute_directory(path: Path, error_message: str) -> int:
    if not path.is_absolute() or ".." in path.parts:
        raise ExportError(error_message)
    current_fd = -1
    try:
        current_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        for part in path.parts[1:]:
            next_fd = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=current_fd,
            )
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except OSError as error:
        if current_fd >= 0:
            os.close(current_fd)
        raise ExportError(error_message) from error


def _write_all(file_fd: int, content: bytes) -> None:
    view = memoryview(content)
    written = 0
    while written < len(view):
        count = os.write(file_fd, view[written:])
        if count <= 0:
            raise OSError("short write")
        written += count


def _unlink_if_inode(
    parent_fd: int,
    name: str,
    expected_inode: tuple[int, int],
) -> None:
    try:
        current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (current.st_dev, current.st_ino) == expected_inode:
            os.unlink(name, dir_fd=parent_fd)
    except FileNotFoundError:
        return
