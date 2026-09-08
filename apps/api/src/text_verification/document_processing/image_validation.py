from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf

from text_verification.domain.documents import FileType

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_START_OF_FRAME_MARKERS = frozenset(
    {
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
    }
)
_PYMUPDF: Any = pymupdf


class ImageValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ValidatedImage:
    content: bytes
    width: int
    height: int
    samples: bytes
    stride: int
    channels: int
    dpi: float = 72.0


def validate_image_file(
    path: Path,
    file_type: FileType,
    *,
    max_file_bytes: int,
    max_width: int = 5_000,
    max_height: int = 5_000,
    max_pixels: int = 20_000_000,
    max_decoded_bytes: int = 60_000_000,
) -> ValidatedImage:
    if file_type not in {FileType.PNG, FileType.JPG}:
        raise ImageValidationError("Unsupported image type.")
    size = path.stat().st_size
    if size <= 0 or size > max_file_bytes:
        raise ImageValidationError("Image exceeds the configured size limit.")
    content = path.read_bytes()
    detected_type, width, height = _image_header(content)
    if detected_type is not file_type:
        raise ImageValidationError("Upload content does not match its image extension.")
    if (
        width <= 0
        or height <= 0
        or width > max_width
        or height > max_height
        or width * height > max_pixels
        or width * height * 4 > max_decoded_bytes
    ):
        raise ImageValidationError("Image dimensions exceed configured limits.")
    try:
        pixmap: Any = _PYMUPDF.Pixmap(content)
    except (RuntimeError, ValueError) as error:
        raise ImageValidationError("Image payload could not be fully decoded.") from error
    try:
        if pixmap.width != width or pixmap.height != height:
            raise ImageValidationError(
                "Decoded image dimensions do not match its header."
            )
        if pixmap.stride * pixmap.height > max_decoded_bytes:
            raise ImageValidationError(
                "Image exceeds the configured decoded image byte limit."
            )
        return ValidatedImage(
            content=content,
            width=width,
            height=height,
            samples=bytes(pixmap.samples),
            stride=pixmap.stride,
            channels=pixmap.n,
            dpi=float(pixmap.yres) if pixmap.yres > 0 else 72.0,
        )
    finally:
        del pixmap


def _image_header(content: bytes) -> tuple[FileType, int, int]:
    if content.startswith(_PNG_SIGNATURE):
        if len(content) < 33 or content[12:16] != b"IHDR":
            raise ImageValidationError("PNG header is invalid.")
        return (
            FileType.PNG,
            int.from_bytes(content[16:20], "big"),
            int.from_bytes(content[20:24], "big"),
        )
    if content.startswith(b"\xff\xd8"):
        width, height = _jpeg_dimensions(content)
        return FileType.JPG, width, height
    raise ImageValidationError("Image signature is unsupported.")


def _jpeg_dimensions(content: bytes) -> tuple[int, int]:
    offset = 2
    while offset < len(content):
        while offset < len(content) and content[offset] == 0xFF:
            offset += 1
        if offset >= len(content):
            break
        marker = content[offset]
        offset += 1
        if marker in {0xD8, 0xD9}:
            continue
        if marker == 0xDA:
            break
        if offset + 2 > len(content):
            break
        segment_length = int.from_bytes(content[offset : offset + 2], "big")
        if segment_length < 2 or offset + segment_length > len(content):
            break
        if marker in _JPEG_START_OF_FRAME_MARKERS:
            if segment_length < 7:
                break
            height = int.from_bytes(content[offset + 3 : offset + 5], "big")
            width = int.from_bytes(content[offset + 5 : offset + 7], "big")
            return width, height
        offset += segment_length
    raise ImageValidationError("JPEG header is invalid.")
