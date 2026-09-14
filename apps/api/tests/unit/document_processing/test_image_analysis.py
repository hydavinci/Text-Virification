from __future__ import annotations

import tracemalloc
from pathlib import Path

import cv2
import numpy as np
import pymupdf
import pytest
from PIL import Image

from text_verification.document_processing.errors import OcrProcessingError
from text_verification.document_processing.image_regions import detect_non_text_image_regions
from text_verification.document_processing.image_validation import (
    ValidatedImage,
    normalize_image_pixmap,
    validate_image_file,
)
from text_verification.domain.documents import FileType


def test_cmyk_jpeg_is_normalized_before_region_detection(tmp_path: Path) -> None:
    source = tmp_path / "cmyk.jpg"
    image = Image.new("CMYK", (240, 180), (0, 0, 0, 0))
    image.paste((0, 0, 0, 255), (130, 70, 220, 160))
    image.save(source, quality=100, subsampling=0)
    assert pymupdf.Pixmap(source).colorspace.n == 4
    validated = validate_image_file(source, FileType.JPG, max_file_bytes=1_000_000)
    assert validated.channels == 3
    regions = detect_non_text_image_regions(validated, [])
    assert [region.bbox for region in regions] == [(130.0, 70.0, 220.0, 160.0)]


def test_region_detection_has_bounded_low_memory_peak() -> None:
    # Import/initialize native detection outside the measurement.
    cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
    pixels = np.full((600, 1000, 3), 255, dtype=np.uint8)
    pixels[200:400, 500:800] = (30, 80, 160)
    image = ValidatedImage(b"", 1000, 600, pixels.tobytes(), 3000, 3)
    tracemalloc.start()
    try:
        regions = detect_non_text_image_regions(image, [])
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert [region.bbox for region in regions] == [(500.0, 200.0, 800.0, 400.0)]
    assert peak < len(image.samples) * 5, f"peak={peak}, samples={len(image.samples)}"


def test_alpha_normalization_avoids_full_raster_python_copies() -> None:
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 1000, 600), True)
    pixmap.clear_with()
    pixmap.set_rect(pymupdf.IRect(500, 200, 800, 400), (0, 0, 0, 128))
    tracemalloc.start()
    try:
        normalized = normalize_image_pixmap(pixmap)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert normalized.pixel(0, 0) == (255, 255, 255)
    assert normalized.pixel(600, 300) == (127, 127, 127)
    assert peak < 600_000, f"peak={peak}"


def test_transparent_background_does_not_hide_opaque_black_content(tmp_path: Path) -> None:
    source = tmp_path / "alpha.png"
    image = Image.new("RGBA", (240, 180), (0, 0, 0, 0))
    image.paste((0, 0, 0, 255), (130, 70, 220, 160))
    image.save(source)
    validated = validate_image_file(source, FileType.PNG, max_file_bytes=1_000_000)
    regions = detect_non_text_image_regions(validated, [])
    assert [region.bbox for region in regions] == [(130.0, 70.0, 220.0, 160.0)]


def test_region_detection_reports_memory_exhaustion(monkeypatch: pytest.MonkeyPatch) -> None:
    pixels = np.full((100, 100, 3), 255, dtype=np.uint8)
    image = ValidatedImage(b"", 100, 100, pixels.tobytes(), 300, 3)

    def exhausted(*args: object, **kwargs: object) -> None:
        raise MemoryError

    monkeypatch.setattr(np, "zeros", exhausted)
    with pytest.raises(OcrProcessingError) as raised:
        detect_non_text_image_regions(image, [])
    assert raised.value.code == "ocr_resource_exhausted"


@pytest.mark.parametrize("mode", ["RGB", "L"])
def test_region_detection_preserves_nonwhite_background_and_exclusions(
    tmp_path: Path, mode: str,
) -> None:
    source = tmp_path / "gray.png"
    image = Image.new(mode, (400, 200), 150 if mode == "L" else (150, 150, 150))
    image.paste(0 if mode == "L" else (0, 0, 0), (20, 40, 100, 160))
    image.paste(0 if mode == "L" else (0, 0, 0), (260, 40, 340, 160))
    image.save(source)
    validated = validate_image_file(source, FileType.PNG, max_file_bytes=1_000_000)
    regions = detect_non_text_image_regions(
        validated, [], excluded_bboxes=[(20.0, 40.0, 100.0, 160.0)]
    )
    assert [region.bbox for region in regions] == [(260.0, 40.0, 340.0, 160.0)]
