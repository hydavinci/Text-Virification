from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pymupdf

from text_verification.document_processing.pdf_models import (
    PdfPageKind,
    PdfPageMetadata,
    PdfResourceLimits,
)

SUBSTANTIAL_RASTER_COVERAGE = 0.5
MIN_USABLE_NATIVE_TEXT_CHARACTERS = 1
_PYMUPDF: Any = pymupdf


def classify_pages(
    source_path: Path,
    *,
    limits: PdfResourceLimits | None = None,
) -> list[PdfPageKind]:
    from text_verification.parsers.errors import PdfResourceLimitError

    resolved_limits = limits or PdfResourceLimits()
    with _PYMUPDF.open(source_path) as document:
        if document.page_count > resolved_limits.max_pages:
            raise PdfResourceLimitError(
                limit="max_pages",
                maximum=resolved_limits.max_pages,
                actual=document.page_count,
            )
        return [
            _classify_limited_page(page, page_number + 1, resolved_limits).kind
            for page_number, page in enumerate(document)
        ]


def _classify_limited_page(
    page: Any,
    page_number: int,
    limits: PdfResourceLimits,
) -> PdfPageMetadata:
    from text_verification.parsers.errors import PdfResourceLimitError

    raw_images = page.get_images(full=True)
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
    rectangles: list[tuple[float, float, float, float]] = []
    rectangle_count = 0
    for xref in xrefs:
        xref_rectangles = page.get_image_rects(xref)
        rectangle_count += len(xref_rectangles)
        if rectangle_count > limits.max_image_rectangles_per_page:
            raise PdfResourceLimitError(
                limit="max_image_rectangles_per_page",
                maximum=limits.max_image_rectangles_per_page,
                actual=rectangle_count,
            )
        rectangles.extend(
            _normalized_bbox(page, rectangle)
            for rectangle in xref_rectangles
            if not rectangle.is_empty
        )
    return classify_page(page, page_number, image_rectangles=rectangles)


def classify_page(
    page: Any,
    page_number: int,
    *,
    image_rectangles: Iterable[tuple[float, float, float, float]] | None = None,
) -> PdfPageMetadata:
    page_bbox = _as_bbox(page.rect)
    page_area = max((page_bbox[2] - page_bbox[0]) * (page_bbox[3] - page_bbox[1]), 1.0)
    text_length = len(_normalize_text(page.get_text("text")))
    rectangles = (
        tuple(image_rectangles)
        if image_rectangles is not None
        else tuple(_image_rectangles(page))
    )
    image_coverage = _image_coverage(rectangles, page_bbox)
    text_density = text_length / page_area

    has_usable_text = text_length >= MIN_USABLE_NATIVE_TEXT_CHARACTERS
    has_bounded_raster = image_coverage > 0.0
    if not has_usable_text and has_bounded_raster:
        kind = PdfPageKind.SCANNED
    elif image_coverage >= SUBSTANTIAL_RASTER_COVERAGE and has_usable_text:
        kind = PdfPageKind.MIXED
    else:
        kind = PdfPageKind.TEXT

    return PdfPageMetadata(
        page=page_number,
        kind=kind,
        page_bbox=page_bbox,
        text_length=text_length,
        text_density=round(text_density, 6),
        image_coverage=round(image_coverage, 6),
        ocr_required=kind in {PdfPageKind.SCANNED, PdfPageKind.MIXED},
    )


def _normalize_text(text: str) -> str:
    return " ".join(text.split())


def _image_rectangles(page: Any) -> list[tuple[float, float, float, float]]:
    rectangles: list[tuple[float, float, float, float]] = []
    seen_xrefs: set[int] = set()
    for image in page.get_images(full=True):
        xref = int(image[0])
        if xref in seen_xrefs:
            continue
        seen_xrefs.add(xref)
        rectangles.extend(
            _normalized_bbox(page, rectangle)
            for rectangle in page.get_image_rects(xref)
            if not rectangle.is_empty
        )
    return rectangles


def _image_coverage(
    rectangles: Iterable[tuple[float, float, float, float]],
    page_rect: tuple[float, float, float, float],
) -> float:
    clipped = [
        intersection
        for rectangle in rectangles
        if (intersection := _intersection(rectangle, page_rect)) is not None
    ]
    page_area = max((page_rect[2] - page_rect[0]) * (page_rect[3] - page_rect[1]), 1.0)
    return min(_union_area(clipped) / page_area, 1.0)


def _union_area(rectangles: list[tuple[float, float, float, float]]) -> float:
    y_coordinates = sorted(
        {coordinate for rectangle in rectangles for coordinate in rectangle[1::2]}
    )
    area = 0.0
    for bottom, top in zip(y_coordinates, y_coordinates[1:], strict=False):
        if top <= bottom:
            continue
        intervals = sorted(
            (rectangle[0], rectangle[2])
            for rectangle in rectangles
            if rectangle[1] < top and rectangle[3] > bottom
        )
        covered_width = 0.0
        current_start: float | None = None
        current_end: float | None = None
        for start, end in intervals:
            if current_start is None or current_end is None:
                current_start, current_end = start, end
            elif start > current_end:
                covered_width += current_end - current_start
                current_start, current_end = start, end
            else:
                current_end = max(current_end, end)
        if current_start is not None and current_end is not None:
            covered_width += current_end - current_start
        area += covered_width * (top - bottom)
    return area


def _intersection(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> tuple[float, float, float, float] | None:
    x0, y0 = max(first[0], second[0]), max(first[1], second[1])
    x1, y1 = min(first[2], second[2]), min(first[3], second[3])
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


def _as_bbox(rectangle: Any) -> tuple[float, float, float, float]:
    return (
        float(rectangle.x0),
        float(rectangle.y0),
        float(rectangle.x1),
        float(rectangle.y1),
    )


def _normalized_bbox(page: Any, rectangle: Any) -> tuple[float, float, float, float]:
    normalized = _PYMUPDF.Rect(rectangle) * page.rotation_matrix
    return _as_bbox(normalized)
