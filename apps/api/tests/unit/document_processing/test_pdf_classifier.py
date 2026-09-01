from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pymupdf
import pytest

from text_verification.document_processing import pdf_classifier as pdf_classifier_module
from text_verification.document_processing.pdf_classifier import classify_pages
from text_verification.document_processing.pdf_models import PdfPageKind, PdfResourceLimits
from text_verification.parsers.errors import PdfResourceLimitError

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


def test_classifies_empty_and_vector_only_pages_as_text(tmp_path: Path) -> None:
    document = pymupdf.open()
    document.new_page()
    vector_page = document.new_page()
    vector_page.draw_rect(pymupdf.Rect(20, 20, 220, 220), color=(0, 0, 0))
    source = tmp_path / "empty-and-vector.pdf"
    document.save(source)
    document.close()

    assert classify_pages(source) == [PdfPageKind.TEXT, PdfPageKind.TEXT]


def test_small_decorative_image_does_not_override_native_text(
    pdf_fixture: callable[[str], Path],
) -> None:
    assert classify_pages(pdf_fixture("text-page.pdf")) == [PdfPageKind.TEXT]


def test_short_native_text_overlay_on_a_substantial_raster_is_mixed(
    pdf_fixture: callable[[str], Path],
) -> None:
    assert classify_pages(pdf_fixture("short-overlay.pdf")) == [PdfPageKind.MIXED]


def test_classify_pages_applies_the_shared_page_limit(
    pdf_fixture: callable[[str], Path],
) -> None:
    source = pdf_fixture("mixed-pages.pdf")

    assert classify_pages(source, limits=PdfResourceLimits(max_pages=2)) == [
        PdfPageKind.TEXT,
        PdfPageKind.SCANNED,
    ]
    with pytest.raises(PdfResourceLimitError, match="max_pages"):
        classify_pages(source, limits=PdfResourceLimits(max_pages=1))


class _RecordingPage:
    rect = pymupdf.Rect(0, 0, 100, 100)
    rotation_matrix = pymupdf.Matrix(1, 1)

    def __init__(
        self,
        rectangles_by_xref: dict[int, list[pymupdf.Rect]],
        calls: list[int],
    ) -> None:
        self._rectangles_by_xref = rectangles_by_xref
        self._calls = calls

    def get_images(self, *, full: bool) -> list[tuple[int]]:
        assert full is True
        return [(xref,) for xref in self._rectangles_by_xref]

    def get_image_rects(self, xref: int) -> list[pymupdf.Rect]:
        self._calls.append(xref)
        return self._rectangles_by_xref[xref]

    def get_text(self, option: str) -> str:
        assert option == "text"
        return "native text"


class _RecordingDocument:
    def __init__(self, page: _RecordingPage) -> None:
        self._page = page
        self.page_count = 1

    def __enter__(self) -> _RecordingDocument:
        return self

    def __exit__(self, *args: Any) -> None:
        del args

    def __iter__(self) -> Any:
        return iter((self._page,))


def test_classify_pages_accepts_the_exact_cumulative_rectangle_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[int] = []
    page = _RecordingPage(
        {
            11: [pymupdf.Rect(1, 1, 5, 5)],
            22: [pymupdf.Rect(6, 1, 10, 5)],
        },
        calls,
    )
    monkeypatch.setattr(
        pdf_classifier_module._PYMUPDF,
        "open",
        lambda source: _RecordingDocument(page),
    )

    assert classify_pages(
        tmp_path / "unused.pdf",
        limits=PdfResourceLimits(max_image_rectangles_per_page=2),
    ) == [PdfPageKind.TEXT]
    assert calls == [11, 22]


def test_classify_pages_stops_querying_xrefs_immediately_after_cumulative_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[int] = []
    page = _RecordingPage(
        {
            11: [pymupdf.Rect(1, 1, 5, 5)],
            22: [
                pymupdf.Rect(6, 1, 10, 5),
                pymupdf.Rect(11, 1, 15, 5),
            ],
            33: [pymupdf.Rect(16, 1, 20, 5)],
        },
        calls,
    )
    monkeypatch.setattr(
        pdf_classifier_module._PYMUPDF,
        "open",
        lambda source: _RecordingDocument(page),
    )

    with pytest.raises(PdfResourceLimitError) as raised:
        classify_pages(
            tmp_path / "unused.pdf",
            limits=PdfResourceLimits(max_image_rectangles_per_page=2),
        )

    assert raised.value.actual == 3
    assert calls == [11, 22]


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
