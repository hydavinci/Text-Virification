from __future__ import annotations

import base64
import re
from bisect import bisect_left
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unicodedata import normalize

import fitz  # type: ignore[import-untyped]
from docx import Document

from text_verification.application.original_preview import OriginalPreviewError
from text_verification.compatibility.docx_traversal import iter_docx_paragraphs
from text_verification.compatibility.exporters import ExportError, export_original
from text_verification.compatibility.parser import strip_html
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
_HORIZONTAL_WHITESPACE = re.compile(r"[^\S\r\n\v\f\x1c-\x1e\x85\u2028\u2029]+")
_SYMBOL_FONTS = frozenset({
    "OpenSymbol", "Wingdings", "Wingdings2", "Wingdings3", "Webdings", "ZapfDingbats",
})


@dataclass(frozen=True)
class _Glyph:
    text: str
    page: int
    x: float
    y: float
    width: float
    height: float
    line: int = 0
    symbol: bool = False


def _normalized(text: str) -> tuple[str, list[int]]:
    characters: list[str] = []
    offsets: list[int] = []
    for offset, character in enumerate(text):
        for value in normalize("NFKC", character):
            if not value.isspace() and value != "\u00ad":
                characters.append(value)
                offsets.append(offset)
    return "".join(characters), offsets


def _same_line(first: _Glyph, second: _Glyph) -> bool:
    return (first.page, first.line) == (second.page, second.line)


def _in_anchor_gap(glyph: _Glyph, left: _Glyph, right: _Glyph) -> bool:
    if glyph.page != left.page or glyph.page != right.page:
        return False
    horizontal = abs(left.x + left.width / 2 - right.x - right.width / 2) >= abs(
        left.y + left.height / 2 - right.y - right.height / 2,
    )
    # Swap axes for rotated pages so the measured gap follows the text direction.
    (start, cross, size, cross_size), first, last = [
        (item.x, item.y, item.width, item.height) if horizontal
        else (item.y, item.x, item.height, item.width)
        for item in (glyph, left, right)
    ]
    first, last = sorted((first, last))
    first_center, last_center = first[1] + first[3] / 2, last[1] + last[3] / 2
    tolerance = max(first[3], last[3]) * 0.3
    return (
        first[0] + first[2] - 0.1 <= start
        and start + size <= last[0] + 0.1
        and abs(first_center - last_center) <= tolerance
        and abs(cross + cross_size / 2 - (first_center + last_center) / 2) <= tolerance
    )


def _whitespace_in_gap(
    left: _Glyph,
    right: _Glyph,
    glyphs: list[_Glyph],
    by_page: dict[int, list[tuple[float, int]]],
    budget: int,
) -> tuple[list[_Glyph], int]:
    height = max(left.height, right.height)
    center = (left.y + left.height / 2 + right.y + right.height / 2) / 2
    gap_start, gap_end = left.x + left.width, right.x
    if (
        left.page != right.page or gap_end <= gap_start
        or abs(left.y + left.height / 2 - right.y - right.height / 2) > height * 0.3
    ):
        return [], 0
    entries = by_page.get(left.page, [])
    first = bisect_left(entries, (center - height, -1))
    last = bisect_left(entries, (center + height, -1))
    candidates: list[_Glyph] = []
    checks = 0
    for position in range(first, last):
        checks += 1
        if checks > budget:
            return [], checks
        glyph = glyphs[entries[position][1]]
        if (
            abs(glyph.y + glyph.height / 2 - center) > height * 0.3
            or glyph.x + glyph.width <= gap_start + 0.1
            or glyph.x >= gap_end - 0.1
        ):
            continue
        if not glyph.text.isspace():
            return [], checks
        # Underlined Office runs can overprint spaces with slightly different
        # font advances. Keep only the measured part between trusted anchors.
        start = max(glyph.x, gap_start)
        end = min(glyph.x + glyph.width, gap_end)
        candidate = replace(glyph, x=start, width=end - start)
        if not _in_anchor_gap(candidate, left, right):
            return [], checks
        candidates.append(candidate)
    return sorted(candidates, key=lambda glyph: glyph.x), checks


def _map_whitespace(
    text: str,
    glyphs: list[_Glyph],
    pages: list[LayoutPage],
    anchors: dict[int, tuple[int, int]],
) -> None:
    if not _HORIZONTAL_WHITESPACE.search(text):
        return
    trusted: dict[int, tuple[int, int]] = {}
    for token in re.finditer(r"\S+", text):
        token_first = anchors.get(token.start())
        token_last = anchors.get(token.end() - 1)
        if token_first is None or token_last is None:
            continue
        rendered = "".join(glyph.text for glyph in glyphs[token_first[0]:token_last[1] + 1])
        if _normalized(token.group())[0] != _normalized(rendered)[0]:
            continue
        trusted[token.start()] = token_first
        trusted[token.end() - 1] = token_last
    by_page: dict[int, list[tuple[float, int]]] = {}
    for index, glyph in enumerate(glyphs):
        by_page.setdefault(glyph.page, []).append((glyph.y, index))
    for entries in by_page.values():
        entries.sort()
    candidate_checks = 0
    for match in _HORIZONTAL_WHITESPACE.finditer(text):
        start, end = match.span()
        left = trusted.get(start - 1)
        right = trusted.get(end)
        if left is not None and right is not None:
            first, last = left[1] + 1, right[0]
        elif left is not None and (end == len(text) or text[end].isspace()):
            anchor = glyphs[left[1]]
            first = last = left[1] + 1
            while (
                last < len(glyphs)
                and _same_line(anchor, glyphs[last])
                and glyphs[last].text.isspace()
            ):
                last += 1
            if last < len(glyphs) and _same_line(anchor, glyphs[last]):
                continue
        elif right is not None and (start == 0 or text[start - 1].isspace()):
            anchor = glyphs[right[0]]
            first = last = right[0]
            while (
                first > 0
                and _same_line(anchor, glyphs[first - 1])
                and glyphs[first - 1].text.isspace()
            ):
                first -= 1
            if first > 0 and _same_line(anchor, glyphs[first - 1]):
                continue
        else:
            continue
        candidates = glyphs[first:last] if first < last else []
        if left is not None and right is not None and (
            not candidates or any(
                not glyph.text.isspace()
                or not _in_anchor_gap(glyph, glyphs[left[1]], glyphs[right[0]])
                for glyph in candidates
            )
        ):
            candidates, checks = _whitespace_in_gap(
                glyphs[left[1]], glyphs[right[0]], glyphs, by_page,
                MAX_MAPPING_WORK - candidate_checks,
            )
            candidate_checks += checks
            if candidate_checks > MAX_MAPPING_WORK:
                return
        if not candidates or any(not glyph.text.isspace() for glyph in candidates):
            continue
        exact = normalize("NFKC", match.group()) == normalize(
            "NFKC", "".join(glyph.text for glyph in candidates),
        )
        if (
            not exact and (left is None or right is None)
            and any(not _same_line(candidates[0], glyph) for glyph in candidates)
        ):
            continue
        for offset, glyph in enumerate(candidates):
            # Office may collapse a whitespace run; keep its measured region
            # rather than inventing separate character positions inside it.
            pages[glyph.page].glyphs.append(LayoutGlyph(
                start=start + offset if exact else start,
                end=start + offset + 1 if exact else end,
                x=glyph.x, y=glyph.y, width=glyph.width, height=glyph.height,
            ))


def _unclaimed_occurrences(
    text: str, value: str, assigned: bytearray, budget: int,
) -> tuple[list[int], int]:
    matches: list[int] = []
    work = len(text)
    if work > budget:
        return [], work
    start = text.find(value)
    while start >= 0:
        work += len(value)
        if work > budget:
            return [], work
        if assigned.find(b"\x01", start, start + len(value)) == -1:
            matches.append(start)
            if len(matches) == 2:
                break
        start = text.find(value, start + 1)
    return matches, work


def _map_glyphs(text: str, glyphs: list[_Glyph], pages: list[LayoutPage]) -> bool:
    source, source_offsets = _normalized(text)
    rendered, rendered_offsets = _normalized("".join(glyph.text for glyph in glyphs))
    if not source:
        return True
    paragraphs = text.splitlines(keepends=True)
    identities = [_normalized(paragraph)[0] for paragraph in paragraphs]
    occurrences = Counter(identity for identity in identities if identity)
    if len(rendered) * len(occurrences) > MAX_MAPPING_WORK:
        return False
    rendered_counts = {identity: rendered.count(identity) for identity in occurrences}
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
        matches = []
        if work <= MAX_MAPPING_WORK:
            matcher = SequenceMatcher(None, source, rendered, autojunk=False)
            matches = [
                (match.a, match.b, match.size)
                for match in matcher.get_matching_blocks()
                if match.size >= 8
            ]
        if sum(size for _, _, size in matches) < 0.8 * len(source):
            matches = []
        paragraph_matches = []
        unique_in_source = set()
        if len(source) * len(occurrences) <= MAX_MAPPING_WORK:
            unique_in_source = {
                identity for identity in occurrences
                if len(identity) >= 8 and rendered_counts[identity] == 1
                and source.count(identity) == 1
            }
        normalized_start = 0
        for identity in identities:
            if identity in unique_in_source:
                paragraph_matches.append((normalized_start, rendered.find(identity), len(identity)))
            normalized_start += len(identity)
        # Tables may be extracted after paragraphs but rendered in document order.
        # Prefer unique whole paragraphs, with longer matches owning overlaps.
        matches = sorted(paragraph_matches, key=lambda match: (-match[2], match[0])) + matches
    # A heading may also occur inside a body paragraph; only additional rendered
    # occurrences can indicate headers completing an otherwise unique body match.
    ambiguous = {
        identity for identity, count in occurrences.items()
        if (rendered_count := rendered_counts[identity]) > count
        and rendered_count > source.count(identity)
    }
    excluded: set[int] = set()
    cursor = 0
    for paragraph, identity in zip(paragraphs, identities, strict=True):
        if identity in ambiguous:
            excluded.update(range(cursor, cursor + len(paragraph)))
        cursor += len(paragraph)
    mapped: dict[int, tuple[int, int]] = {}
    assigned_source = bytearray(len(source))
    assigned_rendered = bytearray(len(rendered))
    source_to_rendered: dict[int, int] = {}

    def assign(source_start: int, rendered_start: int, size: int, *, exclude: bool = False) -> None:
        for offset in range(size):
            source_position = source_start + offset
            rendered_position = rendered_start + offset
            start = source_offsets[source_position]
            if (
                (exclude and start in excluded)
                or assigned_source[source_position] or assigned_rendered[rendered_position]
            ):
                continue
            assigned_source[source_position] = assigned_rendered[rendered_position] = 1
            source_to_rendered[source_position] = rendered_position
            rendered_index = rendered_offsets[rendered_position]
            if start in mapped:
                mapped[start] = (
                    min(mapped[start][0], rendered_index), max(mapped[start][1], rendered_index),
                )
                continue
            glyph = glyphs[rendered_index]
            pages[glyph.page].glyphs.append(LayoutGlyph(
                start=start, end=start + 1, x=glyph.x, y=glyph.y,
                width=glyph.width, height=glyph.height,
            ))
            mapped[start] = (rendered_index, rendered_index)

    for source_start, rendered_start, size in matches:
        assign(source_start, rendered_start, size, exclude=True)

    if len(source) * len(occurrences) <= MAX_MAPPING_WORK:
        boundaries = {0, len(rendered)}
        starts = {0}
        for index in range(1, len(rendered_offsets)):
            if not _same_line(
                glyphs[rendered_offsets[index - 1]], glyphs[rendered_offsets[index]],
            ):
                boundaries.add(index)
                starts.add(index)
        # Checkbox/list markers can be rendered from symbol fonts even when
        # Word's extracted paragraph text does not contain the marker.
        for start in tuple(starts):
            index = start
            while (
                index < len(rendered_offsets)
                and (index == start or index not in boundaries)
                and glyphs[rendered_offsets[index]].symbol
            ):
                index += 1
            starts.add(index)

        remaining: list[tuple[int, str]] = []
        cursor = 0
        for identity in identities:
            if identity and not any(assigned_source[cursor:cursor + len(identity)]):
                remaining.append((cursor, identity))
            cursor += len(identity)

        # Longer paragraphs claim their embedded short words first. A short
        # match must then be unique on both sides and span complete PDF lines.
        budget = MAX_MAPPING_WORK
        for start, identity in sorted(remaining, key=lambda item: -len(item[1])):
            candidates, work = _unclaimed_occurrences(source, identity, assigned_source, budget)
            budget -= work
            if budget < 0:
                break
            if candidates != [start]:
                continue
            candidates, work = _unclaimed_occurrences(rendered, identity, assigned_rendered, budget)
            budget -= work
            if budget < 0:
                break
            if len(candidates) == 1:
                candidate = candidates[0]
                if candidate in starts and candidate + len(identity) in boundaries:
                    assign(start, candidate, len(identity))

        # Repeated table values require both neighboring source characters to
        # already agree on the exact interval, without extra rendered copies.
        for start, identity in remaining:
            budget -= len(source)
            if budget < 0:
                break
            end = start + len(identity)
            if any(assigned_source[start:end]):
                continue
            left, right = source_to_rendered.get(start - 1), source_to_rendered.get(end)
            if (
                left is not None and right is not None
                and right == left + len(identity) + 1
                and left + 1 in starts and right in boundaries
                and rendered[left + 1:right] == identity
                and rendered_counts[identity] == source.count(identity)
            ):
                assign(start, left + 1, len(identity))
    _map_whitespace(text, glyphs, pages, mapped)
    for page in pages:
        page.glyphs.sort(key=lambda glyph: (glyph.start, glyph.end))
    return len(mapped) == len(set(source_offsets))


def _map_docx_stories(
    stories: list[str], glyphs: list[_Glyph], pages: list[LayoutPage],
) -> bool:
    """Require independent story evidence, never concatenated body/header/footer order."""
    if len(stories) * len(glyphs) > MAX_MAPPING_WORK:
        return False
    owners: dict[tuple[int, float, float, float, float], set[int]] = {}
    offset = 0
    complete = True
    for story_index, text in enumerate(stories):
        story_pages = [page.model_copy(update={"glyphs": []}) for page in pages]
        complete = _map_glyphs(text, glyphs, story_pages) and complete
        for page_index, story_page in enumerate(story_pages):
            for glyph in story_page.glyphs:
                location = (page_index, glyph.x, glyph.y, glyph.width, glyph.height)
                owners.setdefault(location, set()).add(story_index)
                pages[page_index].glyphs.append(glyph.model_copy(update={
                    "start": glyph.start + offset, "end": glyph.end + offset,
                }))
        offset += len(text) + 1
    for page_index, page in enumerate(pages):
        unique = [
            glyph for glyph in page.glyphs
            if len(owners[(page_index, glyph.x, glyph.y, glyph.width, glyph.height)]) == 1
        ]
        complete = len(unique) == len(page.glyphs) and complete
        page.glyphs = unique
    return complete


def _render_pages(
    content: bytes, file_type: str, text: str, applied: bool,
    source_stories: list[str] | None = None,
) -> ReviewLayout:
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
                line_index = 0
                for block in raw["blocks"]:
                    for line in block.get("lines", []):
                        for span in line["spans"]:
                            previous_box = None
                            for character in span["chars"]:
                                value = character["c"]
                                raw_box = fitz.Rect(character["bbox"])
                                if (
                                    raw_box.width == 0 and raw_box.height > 0
                                    and not value.isspace() and previous_box is not None
                                    and abs(raw_box.x0 - previous_box.x1) < 0.01
                                    and abs(raw_box.y0 - previous_box.y0) < 0.01
                                    and abs(raw_box.y1 - previous_box.y1) < 0.01
                                ):
                                    # A zero-advance ligature continuation shares
                                    # the preceding character's measured outline.
                                    raw_box = fitz.Rect(previous_box)
                                previous_box = fitz.Rect(raw_box) if not raw_box.is_empty else None
                                box = raw_box * page.rotation_matrix
                                box &= rectangle
                                page_text.append(value)
                                if box.is_empty:
                                    continue
                                for codepoint in value:
                                    glyphs.append(_Glyph(
                                        codepoint, page_index, box.x0, box.y0,
                                        box.width, box.height, line_index,
                                        span["font"].split("+")[-1] in _SYMBOL_FONTS,
                                    ))
                        page_text.append("\n")
                        line_index += 1
                if len(glyphs) > 2 * MAX_LAYOUT_TEXT:
                    raise OriginalPreviewError("文档文字量超过版式定位上限。", 413)
                pages.append(LayoutPage(
                    width=rectangle.width, height=rectangle.height,
                    image=f"data:image/svg+xml;base64,{image}", text="".join(page_text),
                ))
    except (fitz.FileDataError, fitz.EmptyFileError, RuntimeError) as error:
        raise OriginalPreviewError("文档页面无法渲染，原文件未修改。") from error
    complete_mapping = (
        _map_glyphs(text, glyphs, pages) if source_stories is None
        else _map_docx_stories(source_stories, glyphs, pages)
    )
    notice = None
    if not applied:
        notice = "此文件的文字位于图片或扫描图像中，修订保留在右侧；原始图像不变。"
    elif not complete_mapping:
        notice = "部分文字无法精确定位；无法定位的问题会显示提示，请结合右侧上下文审阅。"
    layout = ReviewLayout(pages=pages, revision_applied=applied, notice=notice)
    if len(layout.model_dump_json().encode("utf-8")) > MAX_LAYOUT_BYTES:
        raise OriginalPreviewError("分页预览超过 25 MiB 上限。", 413)
    return layout


def _docx_source_stories(content: bytes) -> list[str]:
    stories: dict[str, list[str]] = {}
    for paragraph in iter_docx_paragraphs(Document(BytesIO(content))):
        text = strip_html(paragraph.text).strip()
        if text:
            stories.setdefault(str(paragraph.part.partname), []).append(text)
    return ["\n".join(paragraphs) for paragraphs in stories.values()]


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
    source_stories: list[str] | None = None
    if file_type in {"docx", "doc", "rtf"}:
        if convert is None:
            raise OriginalPreviewError("文档渲染服务未配置。", 503)
        if text != original_text or file_type in {"docx", "doc"}:
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
                        "原文顺序或修订无法安全映射到原版式；请重新分析或手动修改原文件。"
                    ) from error
        if file_type == "docx":
            source_stories = _docx_source_stories(content)
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
    return _render_pages(content, file_type, text, applied, source_stories)
