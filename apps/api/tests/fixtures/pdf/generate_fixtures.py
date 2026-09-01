from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pymupdf

FIXTURE_DIRECTORY = Path(__file__).parent
PAGE_WIDTH = 240
PAGE_HEIGHT = 240


def _png(width: int, height: int, color: tuple[int, int, int]) -> bytes:
    row = bytes(color) * width
    raw = b"".join(b"\x00" + row for _ in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, level=9))
        + chunk(b"IEND", b"")
    )


def _document() -> pymupdf.Document:
    document = pymupdf.open()
    document.set_metadata(
        {
            "title": "PDF classification test fixture",
            "author": "Text Verification",
            "creationDate": "D:20260101000000Z",
            "modDate": "D:20260101000000Z",
        }
    )
    return document


def _save(document: pymupdf.Document, name: str) -> None:
    document.save(
        FIXTURE_DIRECTORY / name,
        garbage=4,
        deflate=True,
        no_new_id=True,
    )
    document.close()


def _add_text_page(document: pymupdf.Document) -> None:
    page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    page.insert_text(
        (24, 30),
        "Structured text page",
        fontsize=12,
        fontname="helv",
    )
    page.insert_text(
        (24, 50),
        "This page has a useful text layer.",
        fontsize=10,
        fontname="helv",
    )

    x0, y0, cell_width, cell_height = 24, 72, 70, 24
    for column in range(3):
        x = x0 + column * cell_width
        page.draw_line((x, y0), (x, y0 + cell_height * 2))
    for row in range(3):
        y = y0 + row * cell_height
        page.draw_line((x0, y), (x0 + cell_width * 2, y))
    for text, x, y in (
        ("A1", 34, 88),
        ("B1", 104, 88),
        ("A2", 34, 112),
        ("B2", 104, 112),
    ):
        page.insert_text((x, y), text, fontsize=10, fontname="helv")

    page.insert_image(pymupdf.Rect(200, 200, 220, 220), stream=_png(4, 4, (20, 140, 220)))


def _add_scanned_page(document: pymupdf.Document) -> None:
    page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    page.insert_image(page.rect, stream=_png(24, 24, (220, 220, 220)))


def _add_mixed_page(document: pymupdf.Document) -> None:
    page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    page.insert_image(page.rect, stream=_png(24, 24, (245, 230, 180)))
    page.insert_text((24, 32), "Readable overlay text", fontsize=12, fontname="helv")
    page.insert_text(
        (24, 52),
        "This native text must not trigger OCR.",
        fontsize=10,
        fontname="helv",
    )


def _add_short_overlay_page(document: pymupdf.Document) -> None:
    page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    page.insert_image(page.rect, stream=_png(24, 24, (245, 230, 180)))
    page.insert_text((24, 32), "OCR", fontsize=12, fontname="helv")


def _add_layout_order_page(document: pymupdf.Document) -> None:
    page = document.new_page(width=240, height=160)
    page.insert_text((24, 128), "Bottom", fontsize=12, fontname="helv")
    page.insert_text((24, 32), "Top", fontsize=12, fontname="helv")
    page.insert_text((24, 80), "Alpha", fontsize=12, fontname="helv")
    page.insert_text((54, 80), "Beta", fontsize=12, fontname="cour")


def _add_table_structure_page(document: pymupdf.Document) -> None:
    page = document.new_page(width=240, height=180)
    x0, y0, cell_width, cell_height = 40, 50, 55, 30
    for column in range(4):
        x = x0 + column * cell_width
        page.draw_line((x, y0), (x, y0 + cell_height * 3))
    for row in range(4):
        y = y0 + row * cell_height
        page.draw_line((x0, y), (x0 + cell_width * 3, y))
    page.insert_text((48, 67), "A1", fontsize=10, fontname="helv")
    page.insert_text((48, 80), "A2", fontsize=10, fontname="helv")
    page.insert_text((102, 67), "B1", fontsize=10, fontname="helv")
    page.insert_text((10, 99), "B1", fontsize=10, fontname="helv")


def _add_rotated_cropped_scan(document: pymupdf.Document, rotation: int) -> None:
    page = document.new_page(width=300, height=200)
    crop = pymupdf.Rect(20, 20, 220, 160)
    page.insert_image(crop, stream=_png(24, 24, (220, 220, 220)))
    page.set_cropbox(crop)
    page.set_rotation(rotation)


def _add_duplicate_text_page(document: pymupdf.Document) -> None:
    page = document.new_page(width=240, height=160)
    page.insert_text((24, 112), "Repeat", fontsize=12, fontname="helv")
    page.insert_text((24, 32), "Repeat", fontsize=12, fontname="helv")


def _add_two_images_page(document: pymupdf.Document) -> None:
    page = document.new_page(width=240, height=160)
    page.insert_text((24, 24), "Two images", fontsize=12, fontname="helv")
    page.insert_image(pymupdf.Rect(24, 40, 64, 80), stream=_png(4, 4, (10, 20, 30)))
    page.insert_image(pymupdf.Rect(80, 40, 120, 80), stream=_png(4, 4, (40, 50, 60)))


def _add_repeated_image_page(document: pymupdf.Document) -> None:
    page = document.new_page(width=240, height=160)
    image = _png(4, 4, (10, 20, 30))
    page.insert_image(pymupdf.Rect(24, 40, 64, 80), stream=image)
    page.insert_image(pymupdf.Rect(80, 40, 120, 80), stream=image)


def _add_repeated_span_page(document: pymupdf.Document) -> None:
    page = document.new_page(width=240, height=120)
    page.insert_text((24, 40), "token token", fontsize=12, fontname="helv")


def _add_proportional_span_page(document: pymupdf.Document) -> None:
    page = document.new_page(width=240, height=120)
    page.insert_text((24, 40), "WWWWi", fontsize=12, fontname="helv")


def _add_styled_space_page(document: pymupdf.Document) -> None:
    page = document.new_page(width=240, height=120)
    text = "Alpha"
    page.insert_text((24, 40), text, fontsize=12, fontname="helv")
    next_x = 24 + pymupdf.get_text_length(text, fontname="helv", fontsize=12)
    page.insert_text((next_x, 40), " Beta", fontsize=12, fontname="cour")


def main() -> None:
    text_page = _document()
    _add_text_page(text_page)
    _save(text_page, "text-page.pdf")

    scanned_page = _document()
    _add_scanned_page(scanned_page)
    _save(scanned_page, "scanned-page.pdf")

    mixed_pages = _document()
    _add_text_page(mixed_pages)
    _add_scanned_page(mixed_pages)
    _save(mixed_pages, "mixed-pages.pdf")

    mixed_page = _document()
    _add_mixed_page(mixed_page)
    _save(mixed_page, "mixed-page.pdf")

    short_overlay = _document()
    _add_short_overlay_page(short_overlay)
    _save(short_overlay, "short-overlay.pdf")

    layout_order = _document()
    _add_layout_order_page(layout_order)
    _save(layout_order, "layout-order.pdf")

    table_structure = _document()
    _add_table_structure_page(table_structure)
    _save(table_structure, "table-structure.pdf")

    rotated_cropped_scan_90 = _document()
    _add_rotated_cropped_scan(rotated_cropped_scan_90, 90)
    _save(rotated_cropped_scan_90, "rotated-cropped-scan-90.pdf")

    rotated_cropped_scan_270 = _document()
    _add_rotated_cropped_scan(rotated_cropped_scan_270, 270)
    _save(rotated_cropped_scan_270, "rotated-cropped-scan-270.pdf")

    duplicate_text = _document()
    _add_duplicate_text_page(duplicate_text)
    _save(duplicate_text, "duplicate-text.pdf")

    two_images = _document()
    _add_two_images_page(two_images)
    _save(two_images, "two-images.pdf")

    repeated_image = _document()
    _add_repeated_image_page(repeated_image)
    _save(repeated_image, "repeated-image.pdf")

    repeated_span = _document()
    _add_repeated_span_page(repeated_span)
    _save(repeated_span, "repeated-span.pdf")

    proportional_span = _document()
    _add_proportional_span_page(proportional_span)
    _save(proportional_span, "proportional-span.pdf")

    styled_space = _document()
    _add_styled_space_page(styled_space)
    _save(styled_space, "styled-space.pdf")


if __name__ == "__main__":
    main()
