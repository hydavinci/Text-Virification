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


if __name__ == "__main__":
    main()
