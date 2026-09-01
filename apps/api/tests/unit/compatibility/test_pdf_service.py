from __future__ import annotations

from pathlib import Path

from text_verification.compatibility import service
from text_verification.parsers.pdf_parser import PdfParser

FIXTURE_DIRECTORY = Path(__file__).resolve().parents[2] / "fixtures" / "pdf"


def test_pdf_parse_uploaded_file_uses_canonical_pdf_parser(
    monkeypatch,
) -> None:
    def legacy_pdf_parse(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("legacy PDF parser must not be used")

    monkeypatch.setattr(service, "parse_file", legacy_pdf_parse)
    source_path = FIXTURE_DIRECTORY / "layout-order.pdf"

    assert service.parse_uploaded_file(source_path, "pdf") == PdfParser().parse(source_path).text
