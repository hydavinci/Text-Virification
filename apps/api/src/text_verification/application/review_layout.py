from __future__ import annotations

import base64
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from tempfile import TemporaryDirectory
from unicodedata import normalize

import fitz  # type: ignore[import-untyped]

from text_verification.application.original_preview import OriginalPreviewError
from text_verification.compatibility.exporters import ExportError, export_original
from text_verification.domain.review_layout import (
    MAX_LAYOUT_BYTES,
    MAX_LAYOUT_PAGES,
    MAX_LAYOUT_TEXT,
    LayoutGlyph,
    LayoutPage,
    ReviewLayout,
)

OfficeConverter = Callable[[bytes, str, str], bytes]
MAX_MAPPING_WORK = 5_000_000


@dataclass(frozen=True)
class _Glyph:
    text: str
    page: int
    x: float
    y: float
    width: float
    height: float


def _normalized(text: str) -> tuple[str, list[int]]:
    characters: list[str] = []
    offsets: list[int] = []
    for offset, character in enumerate(text):
        for value in normalize("NFKC", character):
            if not value.isspace() and value != "\u00ad":
                characters.append(value)
                offsets.append(offset)
    return "".join(characters), offsets


def _map_glyphs(text: str, glyphs: list[_Glyph], pages: list[LayoutPage]) -> bool:
    source, source_offsets = _normalized(text)
    rendered, rendered_offsets = _normalized("".join(glyph.text for glyph in glyphs))
    if not source:
        return True
    exact = rendered.find(source)
    if exact >= 0:
        if rendered.find(source, exact + 1) >= 0:
            return False
        matches = [(0, exact, len(source))]
    else:
        source_counts = Counter(source)
        work = sum(
            count * source_counts[character] for character, count in Counter(rendered).items()
        )
        if work > MAX_MAPPING_WORK:
            return False
        matcher = SequenceMatcher(None, source, rendered, autojunk=False)
        matches = [
            (match.a, match.b, match.size)
            for match in matcher.get_matching_blocks()
            if match.size >= 8
        ]
        if sum(size for _, _, size in matches) < 0.8 * len(source):
            return False
    paragraphs = text.splitlines(keepends=True)
    identities = [_normalized(paragraph)[0] for paragraph in paragraphs]
    occurrences = Counter(identity for identity in identities if identity)
    if len(rendered) * len(occurrences) > MAX_MAPPING_WORK:
        return False
    # A heading may also occur inside a body paragraph; only additional rendered
    # occurrences can indicate headers completing an otherwise unique body match.
    ambiguous = {
        identity for identity, count in occurrences.items()
        if (rendered_count := rendered.count(identity)) > count
        and rendered_count > source.count(identity)
    }
    excluded: set[int] = set()
    cursor = 0
    for paragraph, identity in zip(paragraphs, identities, strict=True):
        if identity in ambiguous:
            excluded.update(range(cursor, cursor + len(paragraph)))
        cursor += len(paragraph)
    mapped: set[int] = set()
    for source_start, rendered_start, size in matches:
        for offset in range(size):
            start = source_offsets[source_start + offset]
            if start in mapped or start in excluded:
                continue
            glyph = glyphs[rendered_offsets[rendered_start + offset]]
            pages[glyph.page].glyphs.append(LayoutGlyph(
                start=start, end=start + 1, x=glyph.x, y=glyph.y,
                width=glyph.width, height=glyph.height,
            ))
            mapped.add(start)
    return len(mapped) == len(set(source_offsets))


def _render_pages(content: bytes, file_type: str, text: str, applied: bool) -> ReviewLayout:
    pages: list[LayoutPage] = []
    glyphs: list[_Glyph] = []
    image_bytes = 0
    try:
        with fitz.open(stream=content, filetype=file_type) as document:
            if document.needs_pass or not 0 < len(document) <= MAX_LAYOUT_PAGES:
                raise OriginalPreviewError("无法预览加密文档或超过 80 页的文档。")
            for page in document:
                rectangle = page.rect
                if rectangle.is_empty or rectangle.is_infinite:
                    raise OriginalPreviewError("文档页面尺寸无效。")
                # Outline glyphs preserve sharp text without relying on browser-installed fonts.
                svg = page.get_svg_image(text_as_path=True).encode("utf-8")
                image = base64.b64encode(svg).decode("ascii")
                image_bytes += len(image)
                if image_bytes > MAX_LAYOUT_BYTES:
                    raise OriginalPreviewError("分页预览超过 25 MiB 上限。", 413)
                page_index = len(pages)
                page_text: list[str] = []
                raw = page.get_text(
                    "rawdict", flags=fitz.TEXTFLAGS_RAWDICT & ~fitz.TEXT_PRESERVE_IMAGES,
                )
                for block in raw["blocks"]:
                    for line in block.get("lines", []):
                        for span in line["spans"]:
                            for character in span["chars"]:
                                box = fitz.Rect(character["bbox"]) * page.rotation_matrix
                                box &= rectangle
                                value = character["c"]
                                page_text.append(value)
                                if box.is_empty:
                                    continue
                                for codepoint in value:
                                    glyphs.append(_Glyph(
                                        codepoint, page_index, box.x0, box.y0,
                                        box.width, box.height,
                                    ))
                        page_text.append("\n")
                if len(glyphs) > 2 * MAX_LAYOUT_TEXT:
                    raise OriginalPreviewError("文档文字量超过版式定位上限。", 413)
                pages.append(LayoutPage(
                    width=rectangle.width, height=rectangle.height,
                    image=f"data:image/svg+xml;base64,{image}", text="".join(page_text),
                ))
    except (fitz.FileDataError, fitz.EmptyFileError, RuntimeError) as error:
        raise OriginalPreviewError("文档页面无法渲染，原文件未修改。") from error
    complete_mapping = _map_glyphs(text, glyphs, pages)
    notice = None
    if not applied:
        notice = "此文件的文字位于图片或扫描图像中，修订保留在右侧；原始图像不变。"
    elif not complete_mapping:
        notice = "部分文字无法精确定位；无法定位的问题会显示提示，请结合右侧上下文审阅。"
    layout = ReviewLayout(pages=pages, revision_applied=applied, notice=notice)
    if len(layout.model_dump_json().encode("utf-8")) > MAX_LAYOUT_BYTES:
        raise OriginalPreviewError("分页预览超过 25 MiB 上限。", 413)
    return layout


def render_review_document(
    content: bytes,
    file_type: str,
    original_text: str,
    text: str,
    *,
    convert: OfficeConverter | None = None,
) -> ReviewLayout:
    if max(len(original_text), len(text)) > MAX_LAYOUT_TEXT:
        raise OriginalPreviewError("文档文字量超过版式预览上限。", 413)
    applied = True
    if file_type in {"docx", "doc", "rtf"}:
        if convert is None:
            raise OriginalPreviewError("文档渲染服务未配置。", 503)
        if text != original_text:
            if file_type == "doc":
                content = convert(content, file_type, "docx")
                file_type = "docx"
            with TemporaryDirectory(prefix="review-revision-") as directory:
                source = Path(directory) / f"source.{file_type}"
                source.write_bytes(content)
                try:
                    content = export_original(
                        source, file_type, [], False,
                        original_text=original_text, modified_text=text,
                    ).content
                except ExportError as error:
                    raise OriginalPreviewError(
                        "这次修订无法安全应用到原版式；修订仍保留，请调整修改范围。"
                    ) from error
        content = convert(content, file_type, "pdf")
        file_type = "pdf"
    elif file_type == "pdf" and text != original_text:
        try:
            with fitz.open(stream=content, filetype="pdf") as document:
                has_native_text = any(page.get_text().strip() for page in document)
        except (fitz.FileDataError, fitz.EmptyFileError, RuntimeError) as error:
            raise OriginalPreviewError("PDF 无法读取，原文件未修改。") from error
        if has_native_text:
            with TemporaryDirectory(prefix="review-pdf-") as directory:
                source = Path(directory) / "source.pdf"
                source.write_bytes(content)
                try:
                    content = export_original(
                        source, "pdf", [], False, original_text=original_text, modified_text=text,
                    ).content
                except ExportError as error:
                    raise OriginalPreviewError(
                        "这次修订无法安全应用到 PDF 原版式，可能超出原文字区域。"
                    ) from error
        else:
            applied = False
    elif file_type in {"png", "jpg"}:
        applied = text == original_text
    elif file_type != "pdf":
        raise OriginalPreviewError("此文件不支持分页版式预览。", 415)
    return _render_pages(content, file_type, text, applied)
