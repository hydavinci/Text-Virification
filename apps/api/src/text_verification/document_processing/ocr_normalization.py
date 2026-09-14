from __future__ import annotations

import unicodedata
from bisect import bisect_left, bisect_right, insort
from dataclasses import dataclass

from pydantic import ValidationError

from text_verification.document_processing.errors import OcrLayoutError, OcrOutputError
from text_verification.document_processing.layout import OcrLayoutBox
from text_verification.document_processing.ocr_provider import OcrTextBox

# Remove effectively empty signals without discarding usable low-confidence text.
MIN_USABLE_OCR_CONFIDENCE = 0.01


@dataclass
class OcrResourceLimitError(OcrLayoutError):
    limit: str
    maximum: int
    actual: int

    def __str__(self) -> str:
        return f"OCR {self.limit} limit exceeded ({self.actual} > {self.maximum})."


def normalize_ocr_boxes(
    raw_boxes: object,
    *,
    page_number: int,
    page_bbox: tuple[float, float, float, float],
    raster_width: int,
    raster_height: int,
    max_boxes: int = 5_000,
    max_text_characters: int = 1_000_000,
) -> tuple[OcrLayoutBox, ...]:
    """Validate untrusted provider output and map raster coordinates to the page."""
    if not isinstance(raw_boxes, list):
        raise OcrOutputError("OCR provider must return a list of OcrTextBox values")
    if len(raw_boxes) > max_boxes:
        raise OcrResourceLimitError("max_ocr_boxes_per_page", max_boxes, len(raw_boxes))
    normalized: list[OcrLayoutBox] = []
    text_characters = 0
    page_width = page_bbox[2] - page_bbox[0]
    page_height = page_bbox[3] - page_bbox[1]
    for raw_box in raw_boxes:
        try:
            # Revalidate model instances too: injected providers can bypass constructors.
            box = OcrTextBox.model_validate(
                raw_box.model_dump() if isinstance(raw_box, OcrTextBox) else raw_box
            )
        except (ValidationError, TypeError, ValueError) as error:
            raise OcrOutputError(str(error)) from error
        text_characters += len(box.text)
        if text_characters > max_text_characters:
            raise OcrResourceLimitError(
                "max_ocr_text_chars_per_page", max_text_characters, text_characters
            )
        if any(
            x < 0.0 or x > raster_width or y < 0.0 or y > raster_height
            for x, y in box.bbox
        ):
            raise OcrOutputError("OCR bbox coordinates must be within the rendered page")
        if box.confidence < MIN_USABLE_OCR_CONFIDENCE:
            continue
        normalized.append(OcrLayoutBox(
            page=page_number,
            box_index=0,
            text=box.text,
            confidence=box.confidence,
            quad=tuple(
                (
                    page_bbox[0] + (x / raster_width) * page_width,
                    page_bbox[1] + (y / raster_height) * page_height,
                )
                for x, y in box.bbox
            ),
        ))
    normalized.sort(
        key=lambda box: (box.bbox[1], box.bbox[0], box.text, -box.confidence, box.quad)
    )
    return tuple(
        box.model_copy(update={"box_index": index}) for index, box in enumerate(normalized)
    )


def coalesce_image_ocr_boxes(
    boxes: tuple[OcrLayoutBox, ...], *, max_candidate_checks: int = 250_000,
) -> tuple[OcrLayoutBox, ...]:
    """Keep the strongest near-identical geometry with bounded spatial inspection."""
    ordered = sorted(
        boxes,
        key=lambda box: (
            -box.confidence, unicodedata.normalize("NFKC", box.text).casefold(),
            unicodedata.normalize("NFKC", box.text), box.text, box.quad,
        ),
    )
    winners: list[OcrLayoutBox] = []
    by_x: list[tuple[float, int]] = []
    by_y: list[tuple[float, int]] = []
    exact: set[tuple[tuple[float, float], ...]] = set()
    checks = 0
    for box in ordered:
        if box.quad in exact:
            continue
        exact.add(box.quad)
        x0, y0, x1, y1 = box.bbox
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        tx, ty = max(0.25, (x1 - x0) * 0.03), max(0.25, (y1 - y0) * 0.03)
        xs = bisect_left(by_x, (cx - tx, -1)), bisect_right(by_x, (cx + tx, len(boxes)))
        ys = bisect_left(by_y, (cy - ty, -1)), bisect_right(by_y, (cy + ty, len(boxes)))
        entries, (start, end) = (by_x, xs) if xs[1] - xs[0] <= ys[1] - ys[0] else (by_y, ys)
        duplicate = False
        for position in range(start, end):
            checks += 1
            if checks > max_candidate_checks:
                raise OcrResourceLimitError(
                    "max_ocr_duplicate_candidate_inspections_per_page", max_candidate_checks, checks
                )
            candidate = winners[entries[position][1]]
            a0, b0, a1, b1 = candidate.bbox
            if abs((a0 + a1) / 2 - cx) > tx or abs((b0 + b1) / 2 - cy) > ty:
                continue
            overlap = max(0.0, min(x1, a1) - max(x0, a0)) * max(
                0.0, min(y1, b1) - max(y0, b0)
            )
            union = (x1 - x0) * (y1 - y0) + (a1 - a0) * (b1 - b0) - overlap
            if overlap / max(union, 1e-9) >= 0.95:
                duplicate = True
                break
        if not duplicate:
            insort(by_x, (cx, len(winners)))
            insort(by_y, (cy, len(winners)))
            winners.append(box)
    winners.sort(key=lambda box: (box.bbox[1], box.bbox[0], box.text, box.quad))
    return tuple(
        box.model_copy(update={"box_index": index}) for index, box in enumerate(winners)
    )
