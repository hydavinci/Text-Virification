from __future__ import annotations

import base64
from io import BytesIO

import fitz
import pytest
from fastapi.testclient import TestClient


def test_renderer_rejects_unsupported_types_without_conversion() -> None:
    from text_verification.preview_renderer import app

    with TestClient(app) as client:
        response = client.post("/render/exe", content=b"not a document")
    assert response.status_code == 415


def test_renderer_rejects_invalid_docx_without_invoking_office() -> None:
    from text_verification.preview_renderer import app

    with TestClient(app) as client:
        response = client.post("/render/docx", content=b"not a zip")
    assert response.status_code == 422


def test_renderer_returns_a_bounded_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    from text_verification import preview_renderer

    document = fitz.open()
    document.new_page()
    pdf = document.tobytes()
    document.close()
    from docx import Document

    word = Document()
    word.add_paragraph("A document with layout")
    stream = BytesIO()
    word.save(stream)

    monkeypatch.setattr(preview_renderer, "convert_document", lambda *_args: pdf)
    with TestClient(preview_renderer.app) as client:
        response = client.post("/render/docx", content=stream.getvalue())
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content == pdf
    assert response.headers["cache-control"] == "no-store"


def test_renderer_rejects_oversized_body_before_conversion(monkeypatch: pytest.MonkeyPatch) -> None:
    from text_verification import preview_renderer

    monkeypatch.setattr(preview_renderer, "MAX_PREVIEW_BYTES", 16)
    with TestClient(preview_renderer.app) as client:
        response = client.post("/render/docx", content=b"x" * 17)
    assert response.status_code == 413


def test_renderer_reports_missing_office(monkeypatch: pytest.MonkeyPatch) -> None:
    from text_verification import preview_renderer

    monkeypatch.setattr(preview_renderer.shutil, "which", lambda _name: None)
    with pytest.raises(preview_renderer.PreviewRenderError, match="LibreOffice"):
        preview_renderer.convert_document(b"unused", "docx")


def test_renderer_returns_interactive_pages_for_a_revision() -> None:
    from text_verification.preview_renderer import app

    with fitz.open() as pdf:
        pdf.new_page().insert_text((30, 50), "Original document")
        content = pdf.tobytes()
    with TestClient(app) as client:
        response = client.post("/review/pdf", json={
            "content": base64.b64encode(content).decode("ascii"),
            "original_text": "Original document", "text": "Original document",
        })
    assert response.status_code == 200
    assert response.json()["pages"][0]["glyphs"][0]["start"] == 0
    assert response.json()["pages"][0]["image"].startswith("data:image/svg+xml;base64,")


def test_renderer_rejects_invalid_review_source_and_oversized_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from text_verification import preview_renderer

    with TestClient(preview_renderer.app) as client:
        response = client.post("/review/docx", json={
            "content": "invalid!", "original_text": "", "text": "",
        })
        assert response.status_code == 422
        monkeypatch.setattr(preview_renderer, "MAX_RENDER_REQUEST_BYTES", 16, raising=False)
        assert client.post("/review/docx", content=b"x" * 17).status_code == 413
