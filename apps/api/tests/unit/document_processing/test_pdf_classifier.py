from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pymupdf
import pytest

from text_verification.document_processing.pdf_classifier import classify_pages
from text_verification.document_processing.pdf_models import PdfPageKind

FIXTURE_DIRECTORY = Path(__file__).resolve().parents[2] / "fixtures" / "pdf"


@pytest.fixture
def pdf_fixture() -> callable[[str], Path]:
    return lambda name: FIXTURE_DIRECTORY / name


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        ("text-page.pdf", [PdfPageKind.TEXT]),
        ("scanned-page.pdf", [PdfPageKind.SCANNED]),
        ("mixed-pages.pdf", [PdfPageKind.TEXT, PdfPageKind.SCANNED]),
        ("mixed-page.pdf", [PdfPageKind.MIXED]),
    ],
)
def test_classifies_each_page(
    pdf_fixture: callable[[str], Path],
    fixture: str,
    expected: list[PdfPageKind],
) -> None:
    assert classify_pages(pdf_fixture(fixture)) == expected


def test_classifies_empty_and_vector_only_pages_as_scanned(tmp_path: Path) -> None:
    document = pymupdf.open()
    document.new_page()
    vector_page = document.new_page()
    vector_page.draw_rect(pymupdf.Rect(20, 20, 220, 220), color=(0, 0, 0))
    source = tmp_path / "empty-and-vector.pdf"
    document.save(source)
    document.close()

    assert classify_pages(source) == [PdfPageKind.SCANNED, PdfPageKind.SCANNED]


def test_small_decorative_image_does_not_override_native_text(
    pdf_fixture: callable[[str], Path],
) -> None:
    assert classify_pages(pdf_fixture("text-page.pdf")) == [PdfPageKind.TEXT]


def test_pdf_classification_does_not_import_the_ocr_provider() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "import text_verification.document_processing.pdf_classifier; "
                "module = 'text_verification.document_processing.ocr_provider'; "
                "raise SystemExit(module in sys.modules)"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
