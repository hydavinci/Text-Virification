from __future__ import annotations

import base64
import struct
import zlib
from collections.abc import Iterable
from pathlib import Path
from uuid import uuid4

import pytest
from docx import Document
from docx.enum.section import WD_ORIENT
from docx.oxml.ns import qn

from text_verification.compatibility.exporters import ExportError
from text_verification.document_processing.pdf_models import (
    PdfDocumentMetadata,
    PdfPageKind,
    PdfPageMetadata,
)
from text_verification.domain.documents import (
    DocumentMetadata,
    DocumentModel,
    FileType,
    TextBlock,
)
from text_verification.exporters.docx_reconstruction import (
    DOCX_RECONSTRUCTION,
    DocxReconstructionExporter,
    DocxReconstructionLimits,
)
from text_verification.exporters.registry import ExporterRegistry


class _Block:
    def __init__(
        self,
        kind: str,
        text: str,
        *,
        page: int | None,
        y: float,
        style: dict[str, object] | None = None,
        table_index: int | None = None,
        row_index: int | None = None,
        cell_index: int | None = None,
        source_locator: dict[str, object] | None = None,
    ) -> None:
        self.kind = kind
        self.text = text
        self.page = page
        self.y = y
        self.style = style or {}
        self.table_index = table_index
        self.row_index = row_index
        self.cell_index = cell_index
        self.source_locator = source_locator or {}


def _png(width: int, height: int) -> bytes:
    def chunk(name: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + name
            + data
            + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)
        )

    rows = b"".join(b"\x00" + b"\x00\x00\x00" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def test_reconstructs_structured_content_and_document_metadata(tmp_path: Path) -> None:
    image = _png(120, 60)
    document = _document(
        [
            _Block(
                "heading",
                "标题\n副题",
                page=1,
                y=10,
                style={
                    "level": 0,
                    "font": {
                        "name": "Noto Sans CJK SC",
                        "size": 16.0,
                        "bold": True,
                        "italic": True,
                    },
                },
            ),
            _Block("paragraph", "第一行\n第二行", page=1, y=40),
            _Block(
                "table_cell",
                "名称",
                page=1,
                y=80,
                table_index=0,
                row_index=0,
                cell_index=0,
                source_locator={"table_shape": {"rows": 2, "columns": 2}},
            ),
            _Block(
                "table_cell",
                "值",
                page=1,
                y=80,
                table_index=0,
                row_index=0,
                cell_index=1,
            ),
            _Block(
                "table_cell",
                "甲",
                page=1,
                y=100,
                table_index=0,
                row_index=1,
                cell_index=0,
            ),
            _Block(
                "table_cell",
                "",
                page=1,
                y=100,
                table_index=0,
                row_index=1,
                cell_index=1,
            ),
            _Block(
                "image",
                "图像替代文本",
                page=1,
                y=130,
                source_locator={
                    "image_payload": {
                        "kind": "bytes",
                        "mime_type": "image/png",
                        "data": image,
                    }
                },
            ),
            _Block("paragraph", "表后正文", page=1, y=170),
        ],
        source_name="源标题.docx",
    )

    target = DocxReconstructionExporter().export(document, tmp_path / "rebuilt.docx")

    rebuilt = Document(target)
    assert rebuilt.paragraphs[0].style.name == "Heading 1"
    assert rebuilt.paragraphs[0].text == "标题\n副题"
    heading_run = rebuilt.paragraphs[0].runs[0]
    assert heading_run.bold is True
    assert heading_run.italic is True
    assert heading_run.font.size is not None
    assert heading_run.font.size.pt == 16.0
    run_fonts = heading_run._element.get_or_add_rPr().rFonts
    assert run_fonts is not None
    assert run_fonts.get(qn("w:eastAsia")) == "Noto Sans CJK SC"
    assert rebuilt.paragraphs[1].text == "第一行\n第二行"
    assert rebuilt.tables[0].cell(0, 0).text == "名称"
    assert rebuilt.tables[0].cell(0, 1).text == "值"
    assert rebuilt.tables[0].cell(1, 0).text == "甲"
    assert rebuilt.tables[0].cell(1, 1).text == ""
    assert len(rebuilt.inline_shapes) == 1
    assert rebuilt.inline_shapes[0].width <= (
        rebuilt.sections[0].page_width
        - rebuilt.sections[0].left_margin
        - rebuilt.sections[0].right_margin
    )
    assert rebuilt.paragraphs[-1].text == "表后正文"
    assert "名称" not in "\n".join(paragraph.text for paragraph in rebuilt.paragraphs)
    assert "图像替代文本" not in "\n".join(
        paragraph.text for paragraph in rebuilt.paragraphs
    )
    assert rebuilt.core_properties.title == "源标题"
    assert rebuilt.sections[0].top_margin.pt == 54.0
    assert rebuilt.sections[0].bottom_margin.pt == 54.0
    assert _body_kinds(rebuilt) == ["paragraph", "paragraph", "table", "paragraph", "paragraph"]


def test_orders_shuffled_blocks_by_page_and_vertical_position(tmp_path: Path) -> None:
    image = _png(1, 1)
    source_blocks = [
        _Block("paragraph", "最后", page=2, y=200),
        _Block(
            "table_cell",
            "右",
            page=1,
            y=100,
            table_index=4,
            row_index=0,
            cell_index=1,
            source_locator={"table_shape": {"rows": 1, "columns": 2}},
        ),
        _Block("paragraph", "最先", page=1, y=10),
        _Block(
            "image",
            "",
            page=1,
            y=150,
            source_locator={
                "image_payload": {
                    "kind": "base64",
                    "mime_type": "image/png",
                    "data": base64.b64encode(image).decode("ascii"),
                }
            },
        ),
        _Block(
            "table_cell",
            "左",
            page=1,
            y=100,
            table_index=4,
            row_index=0,
            cell_index=0,
        ),
    ]
    document = _document(source_blocks)

    target = DocxReconstructionExporter().export(document, tmp_path / "ordered.docx")

    rebuilt = Document(target)
    assert _body_semantics(rebuilt) == [
        ("paragraph", "最先"),
        ("table", (("左", "右"),)),
        ("paragraph", ""),
        ("paragraph", "最后"),
    ]


def test_registry_resolves_explicit_docx_reconstruction_format() -> None:
    exporter = DocxReconstructionExporter()
    registry = ExporterRegistry([exporter])

    assert registry.get(DOCX_RECONSTRUCTION) is exporter


def test_reconstruction_has_deterministic_semantic_roundtrip(tmp_path: Path) -> None:
    document = _document(
        [
            _Block("heading", "标题", page=1, y=10, style={"level": 2}),
            _Block("paragraph", "正文", page=1, y=40),
            _Block(
                "table_cell",
                "单元格",
                page=1,
                y=80,
                table_index=0,
                row_index=0,
                cell_index=0,
            ),
        ]
    )
    exporter = DocxReconstructionExporter()

    first = Document(exporter.export(document, tmp_path / "first.docx"))
    second = Document(exporter.export(document, tmp_path / "second.docx"))

    assert _body_semantics(first) == _body_semantics(second)
    assert _body_semantics(first) == [
        ("paragraph", "标题"),
        ("paragraph", "正文"),
        ("table", (("单元格",),)),
    ]


@pytest.mark.parametrize(
    "blocks",
    [
        [
            _Block(
                "table_cell",
                "A",
                page=1,
                y=10,
                table_index=0,
                row_index=0,
                cell_index=0,
            ),
            _Block(
                "table_cell",
                "B",
                page=1,
                y=20,
                table_index=0,
                row_index=0,
                cell_index=0,
            ),
        ],
        [
            _Block(
                "table_cell",
                "A",
                page=1,
                y=10,
                table_index=0,
                row_index=0,
                cell_index=1,
            )
        ],
        [
            _Block(
                "table_cell",
                "A",
                page=1,
                y=10,
                table_index=0,
                row_index=-1,
                cell_index=0,
            )
        ],
        [
            _Block(
                "table_cell",
                "A",
                page=1,
                y=10,
                table_index=0,
                row_index=0,
                cell_index=0,
                source_locator={"table_shape": {"rows": 1, "columns": 1}},
            ),
            _Block(
                "table_cell",
                "B",
                page=1,
                y=20,
                table_index=0,
                row_index=0,
                cell_index=1,
                source_locator={"table_shape": {"rows": 1, "columns": 2}},
            ),
        ],
        [
            _Block(
                "table_cell",
                "A",
                page=1,
                y=10,
                table_index=1_000_000,
                row_index=0,
                cell_index=0,
            )
        ],
    ],
    ids=[
        "duplicate",
        "sparse",
        "negative-index",
        "conflicting-dimensions",
        "huge-index",
    ],
)
def test_rejects_invalid_table_shapes(tmp_path: Path, blocks: list[_Block]) -> None:
    with pytest.raises(ExportError):
        DocxReconstructionExporter().export(
            _document(blocks),
            tmp_path / "invalid-table.docx",
        )


def test_preserves_explicit_table_merge(tmp_path: Path) -> None:
    document = _document(
        [
            _Block(
                "table_cell",
                "合并",
                page=1,
                y=10,
                table_index=0,
                row_index=0,
                cell_index=0,
                source_locator={
                    "table_shape": {"rows": 2, "columns": 2},
                    "merge": {"row_span": 2, "column_span": 2},
                },
            )
        ]
    )

    rebuilt = Document(
        DocxReconstructionExporter().export(document, tmp_path / "merged.docx")
    )

    top_left = rebuilt.tables[0].cell(0, 0)
    assert top_left.text == "合并"
    assert top_left._tc.tcPr.gridSpan is not None
    assert top_left._tc.tcPr.gridSpan.val == 2
    assert top_left._tc.tcPr.vMerge is not None


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {
            "kind": "base64",
            "mime_type": "image/png",
            "data": "not base64!",
        },
        {
            "kind": "bytes",
            "mime_type": "image/jpeg",
            "data": _png(1, 1),
        },
        {
            "kind": "bytes",
            "mime_type": "image/png",
            "data": b"\x89PNG\r\n\x1a\nspoofed",
        },
        {
            "kind": "bytes",
            "mime_type": "image/png",
            "data": _png(1, 1)[:33],
        },
        {
            "kind": "url",
            "mime_type": "image/png",
            "url": "https://example.invalid/image.png",
        },
        {
            "kind": "bytes",
            "mime_type": "image/png",
            "data": _png(1, 1),
            "unexpected": True,
        },
    ],
    ids=[
        "missing",
        "invalid-base64",
        "mime-spoof",
        "invalid-signature",
        "truncated-image",
        "url",
        "extra-contract-field",
    ],
)
def test_rejects_invalid_image_payloads(
    tmp_path: Path,
    payload: dict[str, object] | None,
) -> None:
    source_locator = {} if payload is None else {"image_payload": payload}
    document = _document(
        [_Block("image", "", page=1, y=10, source_locator=source_locator)]
    )

    with pytest.raises(ExportError):
        DocxReconstructionExporter().export(
            document,
            tmp_path / "invalid-image.docx",
        )


def test_rejects_oversized_image_bytes_and_dimensions(tmp_path: Path) -> None:
    image = _png(4, 4)
    byte_limited = DocxReconstructionExporter(
        limits=DocxReconstructionLimits(max_image_bytes=len(image) - 1)
    )
    dimension_limited = DocxReconstructionExporter(
        limits=DocxReconstructionLimits(max_image_pixels=15)
    )
    document = _document(
        [
            _Block(
                "image",
                "",
                page=1,
                y=10,
                source_locator={
                    "image_payload": {
                        "kind": "bytes",
                        "mime_type": "image/png",
                        "data": image,
                    }
                },
            )
        ]
    )

    with pytest.raises(ExportError, match="size limit"):
        byte_limited.export(document, tmp_path / "too-many-bytes.docx")
    with pytest.raises(ExportError, match="dimensions"):
        dimension_limited.export(document, tmp_path / "too-many-pixels.docx")


def test_reads_only_repository_owned_image_paths(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    image_path = repository_root / "images" / "source.png"
    image_path.parent.mkdir()
    image_path.write_bytes(_png(2, 1))
    document = _document(
        [
            _Block(
                "image",
                "",
                page=1,
                y=10,
                source_locator={
                    "image_payload": {
                        "kind": "repository_path",
                        "mime_type": "image/png",
                        "path": "images/source.png",
                    }
                },
            )
        ]
    )

    rebuilt = Document(
        DocxReconstructionExporter(repository_root=repository_root).export(
            document,
            tmp_path / "repository-image.docx",
        )
    )

    assert len(rebuilt.inline_shapes) == 1


@pytest.mark.parametrize("path", ["../outside.png", "/outside.png"])
def test_rejects_traversal_and_external_image_paths(tmp_path: Path, path: str) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    document = _document(
        [
            _Block(
                "image",
                "",
                page=1,
                y=10,
                source_locator={
                    "image_payload": {
                        "kind": "repository_path",
                        "mime_type": "image/png",
                        "path": path,
                    }
                },
            )
        ]
    )

    with pytest.raises(ExportError, match="repository"):
        DocxReconstructionExporter(repository_root=repository_root).export(
            document,
            tmp_path / "unsafe-image.docx",
        )


def test_rejects_symlinked_repository_image(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(_png(1, 1))
    (repository_root / "linked.png").symlink_to(outside)
    document = _document(
        [
            _Block(
                "image",
                "",
                page=1,
                y=10,
                source_locator={
                    "image_payload": {
                        "kind": "repository_path",
                        "mime_type": "image/png",
                        "path": "linked.png",
                    }
                },
            )
        ]
    )

    with pytest.raises(ExportError, match="repository"):
        DocxReconstructionExporter(repository_root=repository_root).export(
            document,
            tmp_path / "symlink-image.docx",
        )


def test_extracts_pdf_xref_image_from_repository_source(tmp_path: Path) -> None:
    import fitz

    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    pdf_path = repository_root / "source.pdf"
    pdf = fitz.open()
    try:
        page = pdf.new_page()
        xref = page.insert_image(fitz.Rect(0, 0, 20, 10), stream=_png(2, 1))
        pdf.save(pdf_path)
    finally:
        pdf.close()
    document = _document(
        [
            _Block(
                "image",
                "",
                page=1,
                y=10,
                source_locator={
                    "image_payload": {
                        "kind": "pdf_xref",
                        "path": "source.pdf",
                        "xref": xref,
                    }
                },
            )
        ]
    )

    rebuilt = Document(
        DocxReconstructionExporter(repository_root=repository_root).export(
            document,
            tmp_path / "pdf-image.docx",
        )
    )

    assert len(rebuilt.inline_shapes) == 1


def test_applies_pdf_page_size_orientation_and_safe_title(tmp_path: Path) -> None:
    document = _document(
        [_Block("paragraph", "正文", page=1, y=10)],
        source_name="标题\x01.pdf",
        metadata=DocumentMetadata(
            pdf=PdfDocumentMetadata(
                pages=(
                    PdfPageMetadata(
                        page=1,
                        kind=PdfPageKind.TEXT,
                        page_bbox=(0.0, 0.0, 792.0, 612.0),
                        text_length=2,
                        text_density=0.1,
                        image_coverage=0.0,
                        ocr_required=False,
                    ),
                )
            )
        ),
    )

    rebuilt = Document(
        DocxReconstructionExporter().export(document, tmp_path / "landscape.docx")
    )

    section = rebuilt.sections[0]
    assert section.orientation == WD_ORIENT.LANDSCAPE
    assert section.page_width.pt == 792.0
    assert section.page_height.pt == 612.0
    assert rebuilt.core_properties.title == "标题\ufffd"


def test_normalizes_unrepresentable_xml_controls_in_block_text(tmp_path: Path) -> None:
    document = _document([_Block("paragraph", "正文\x01内容", page=1, y=10)])

    rebuilt = Document(
        DocxReconstructionExporter().export(document, tmp_path / "safe-text.docx")
    )

    assert rebuilt.paragraphs[0].text == "正文\ufffd内容"


def test_uses_estimated_font_size_without_mutating_normal_style(tmp_path: Path) -> None:
    document = _document(
        [
            _Block(
                "heading",
                "估算字号",
                page=1,
                y=10,
                style={
                    "level": 99,
                    "estimated_font_size": 19.0,
                    "east_asia_font": "SimSun",
                },
            )
        ]
    )

    rebuilt = Document(
        DocxReconstructionExporter().export(document, tmp_path / "font.docx")
    )

    paragraph = rebuilt.paragraphs[0]
    assert paragraph.style.name == "Heading 9"
    assert paragraph.runs[0].font.size is not None
    assert paragraph.runs[0].font.size.pt == 19.0
    run_fonts = paragraph.runs[0]._element.get_or_add_rPr().rFonts
    assert run_fonts is not None
    assert run_fonts.get(qn("w:eastAsia")) == "SimSun"
    normal_fonts = rebuilt.styles["Normal"].element.get_or_add_rPr().rFonts
    assert normal_fonts is None or normal_fonts.get(qn("w:eastAsia")) != "SimSun"


def test_enforces_table_and_total_element_bounds(tmp_path: Path) -> None:
    table = _document(
        [
            _Block(
                "table_cell",
                "A",
                page=1,
                y=10,
                table_index=0,
                row_index=1,
                cell_index=0,
                source_locator={"table_shape": {"rows": 2, "columns": 1}},
            )
        ]
    )
    paragraphs = _document(
        [
            _Block("paragraph", "A", page=1, y=10),
            _Block("paragraph", "B", page=1, y=20),
        ]
    )

    with pytest.raises(ExportError, match="dimensions"):
        DocxReconstructionExporter(
            limits=DocxReconstructionLimits(max_table_rows=1)
        ).export(table, tmp_path / "table-bound.docx")
    with pytest.raises(ExportError, match="element limit"):
        DocxReconstructionExporter(
            limits=DocxReconstructionLimits(max_output_elements=1)
        ).export(paragraphs, tmp_path / "element-bound.docx")


def test_rejects_invalid_limit_configuration() -> None:
    with pytest.raises(ValueError):
        DocxReconstructionLimits(max_table_rows=0)


def test_does_not_overwrite_existing_or_symlink_targets(tmp_path: Path) -> None:
    document = _document([_Block("paragraph", "正文", page=1, y=10)])
    target = tmp_path / "existing.docx"
    target.write_bytes(b"existing")

    with pytest.raises(ExportError, match="already exists"):
        DocxReconstructionExporter().export(document, target)

    assert target.read_bytes() == b"existing"
    assert not list(tmp_path.glob(".*.uploading"))

    symlink_target = tmp_path / "linked.docx"
    symlink_target.symlink_to(target)
    with pytest.raises(ExportError, match="already exists"):
        DocxReconstructionExporter().export(document, symlink_target)
    assert target.read_bytes() == b"existing"
    assert not list(tmp_path.glob(".*.uploading"))


def test_rejects_symlinked_or_missing_target_parent(tmp_path: Path) -> None:
    document = _document([_Block("paragraph", "正文", page=1, y=10)])
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked"
    linked_parent.symlink_to(real_parent, target_is_directory=True)

    with pytest.raises(ExportError, match="parent"):
        DocxReconstructionExporter().export(document, linked_parent / "output.docx")
    with pytest.raises(ExportError, match="parent"):
        DocxReconstructionExporter().export(
            document,
            tmp_path / "missing" / "output.docx",
        )
    assert list(real_parent.iterdir()) == []


def _document(
    blocks: Iterable[_Block],
    *,
    source_name: str = "source.pdf",
    metadata: DocumentMetadata | None = None,
) -> DocumentModel:
    text_parts: list[str] = []
    canonical_blocks: list[TextBlock] = []
    cursor = 0
    for index, block in enumerate(blocks):
        if text_parts:
            text_parts.append("\n")
            cursor += 1
        start = cursor
        text_parts.append(block.text)
        cursor += len(block.text)
        canonical_blocks.append(
            TextBlock(
                block_id=f"block-{index}",
                kind=block.kind,
                text=block.text,
                global_start=start,
                global_end=cursor,
                block_start=0,
                block_end=len(block.text),
                page=block.page,
                paragraph_index=index if block.kind in {"paragraph", "heading"} else None,
                table_index=block.table_index,
                row_index=block.row_index,
                cell_index=block.cell_index,
                bbox=(10.0, block.y, 110.0, block.y + 10.0),
                parent_id=None,
                style=block.style,
                source_locator={
                    "page": block.page,
                    **block.source_locator,
                },
            )
        )
    return DocumentModel(
        document_id=uuid4(),
        source_version="sha256:test",
        file_type=FileType.PDF,
        source_name=source_name,
        text="".join(text_parts),
        blocks=canonical_blocks,
        parser_name="test",
        parser_version="1",
        metadata=metadata or DocumentMetadata(),
    )


def _body_kinds(document: object) -> list[str]:
    kinds: list[str] = []
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            kinds.append("paragraph")
        elif child.tag == qn("w:tbl"):
            kinds.append("table")
    return kinds


def _body_semantics(document: object) -> list[tuple[str, object]]:
    paragraphs = iter(document.paragraphs)
    tables = iter(document.tables)
    semantics: list[tuple[str, object]] = []
    for kind in _body_kinds(document):
        if kind == "paragraph":
            semantics.append(("paragraph", next(paragraphs).text))
        else:
            table = next(tables)
            semantics.append(
                (
                    "table",
                    tuple(tuple(cell.text for cell in row.cells) for row in table.rows),
                )
            )
    return semantics
