from __future__ import annotations

import importlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from text_verification.document_processing.errors import OcrProcessingError, OcrUnavailableError
from text_verification.document_processing.image_validation import ValidatedImage
from text_verification.document_processing.ocr_provider import OcrTextBox


@dataclass(frozen=True)
class ImageRegion:
    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return float(self.x0), float(self.y0), float(self.x1), float(self.y1)


def detect_non_text_image_regions(
    image: ValidatedImage,
    text_boxes: Sequence[OcrTextBox],
    *,
    excluded_bboxes: Sequence[tuple[float, float, float, float]] = (),
    minimum_width: int = 50,
    minimum_height: int = 50,
    minimum_area: int = 3_000,
    minimum_content_ratio: float = 0.05,
) -> tuple[ImageRegion, ...]:
    try:
        np: Any = importlib.import_module("numpy")
        cv2: Any = importlib.import_module("cv2")
    except ImportError as error:
        raise OcrUnavailableError("Image region detection dependencies are unavailable.") from error
    try:
        return _detect_regions(
            image, text_boxes, np=np, cv2=cv2,
            excluded_bboxes=excluded_bboxes,
            minimum_width=minimum_width,
            minimum_height=minimum_height,
            minimum_area=minimum_area,
            minimum_content_ratio=minimum_content_ratio,
        )
    except MemoryError as error:
        raise OcrProcessingError(
            "Image region detection exceeded available memory.",
            code="ocr_resource_exhausted",
        ) from error
    except cv2.error as error:
        raise OcrProcessingError(
            "Image region detection failed.",
            code=(
                "ocr_resource_exhausted"
                if error.code == cv2.Error.StsNoMem else "ocr_failed"
            ),
        ) from error


def _detect_regions(
    image: ValidatedImage,
    text_boxes: Sequence[OcrTextBox],
    *,
    np: Any,
    cv2: Any,
    excluded_bboxes: Sequence[tuple[float, float, float, float]],
    minimum_width: int,
    minimum_height: int,
    minimum_area: int,
    minimum_content_ratio: float,
) -> tuple[ImageRegion, ...]:

    rows = np.frombuffer(image.samples, dtype=np.uint8).reshape(
        image.height,
        image.stride,
    )
    pixels = rows[:, : image.width * image.channels].reshape(
        image.height,
        image.width,
        image.channels,
    )
    color = pixels[:, :, : min(3, image.channels)]
    border = np.concatenate(
        (color[0, :, :], color[-1, :, :], color[:, 0, :], color[:, -1, :]),
        axis=0,
    )
    background = np.median(border, axis=0)
    # Only the small border statistic is floating point, never the full raster.
    lower = tuple(float(value) for value in np.maximum(0, np.ceil(background - 25)))
    upper = tuple(float(value) for value in np.minimum(255, np.floor(background + 25)))
    content_mask = cv2.inRange(color, lower, upper)
    cv2.bitwise_not(content_mask, dst=content_mask)

    exclusion_mask = np.zeros((image.height, image.width), dtype=np.uint8)
    for box in text_boxes:
        points = np.array(box.bbox, dtype=np.int32).reshape(-1, 1, 2)
        cv2.fillPoly(exclusion_mask, [points], 255)
    for bbox in excluded_bboxes:
        x0, y0, x1, y1 = (_bounded_coordinate(value) for value in bbox)
        cv2.rectangle(exclusion_mask, (x0, y0), (x1, y1), 255, thickness=-1)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
    exclusion_mask = cv2.dilate(exclusion_mask, kernel, iterations=2)
    cv2.bitwise_not(exclusion_mask, dst=exclusion_mask)
    cv2.bitwise_and(content_mask, exclusion_mask, dst=content_mask)

    contours, _ = cv2.findContours(
        content_mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    regions: list[ImageRegion] = []
    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        area = width * height
        if width < minimum_width or height < minimum_height or area < minimum_area:
            continue
        region_content = content_mask[y : y + height, x : x + width]
        if float(np.count_nonzero(region_content)) / float(region_content.size) < (
            minimum_content_ratio
        ):
            continue
        regions.append(ImageRegion(x, y, x + width, y + height))
    return tuple(sorted(regions, key=lambda region: (region.y0, region.x0)))


def _bounded_coordinate(value: float) -> int:
    return max(0, int(round(value)))
