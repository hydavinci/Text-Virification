from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from uuid import UUID
from zipfile import ZipFile

from docx import Document
from fastapi import FastAPI
from fastapi.testclient import TestClient

from text_verification.config import Settings, get_settings


def override_storage(app: FastAPI, storage_root: Path) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        storage_root=storage_root,
        max_upload_bytes=1024 * 1024,
    )


def test_analyze_direct_text_supports_legacy_options(
    app: FastAPI,
    client: TestClient,
    tmp_path: Path,
) -> None:
    override_storage(app, tmp_path)

    response = client.post(
        "/api/v1/analyze",
        data={
            "text": "帐号包含禁用词和AI，联系 test@example.com。台湾产品全球领先。",
            "scenario": "business",
            "enable_security": "true",
            "enable_sensitive": "true",
            "enable_ad_extreme": "true",
            "custom_glossary": json.dumps(
                [{"original": "AI", "standard": "人工智能"}],
                ensure_ascii=False,
            ),
            "banned_words": json.dumps(["禁用词"], ensure_ascii=False),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "success",
        "filename",
        "text",
        "stats",
        "issues",
        "summary",
        "file_id",
        "file_ext",
        "scenario",
        "document_id",
        "verification_run_id",
        "source_version",
        "execution_mode",
        "degradation",
    }
    assert payload["success"] is True
    assert payload["scenario"] == "business"
    assert payload["file_id"] is None
    assert UUID(payload["document_id"])
    assert UUID(payload["verification_run_id"])
    assert payload["source_version"].startswith("sha256:")
    assert payload["execution_mode"] == "rules_with_optional_llm"
    assert payload["degradation"] == {
        "is_degraded": True,
        "reasons": ["llm_review_disabled"],
    }
    assert payload["stats"]["char_count"] == len(payload["text"])
    assert payload["issues"]
    assert UUID(payload["issues"][0]["issue_id"])
    assert payload["issues"][0]["position"] < payload["issues"][0]["end_position"]
    issue_types = {issue["type"] for issue in payload["issues"]}
    assert {
        "typo",
        "custom_term",
        "banned_word",
        "pii_email",
        "sensitive_territory",
        "ad_extreme",
    } <= issue_types


def test_upload_and_export_txt_from_uuid_scoped_storage(
    app: FastAPI,
    client: TestClient,
    tmp_path: Path,
) -> None:
    override_storage(app, tmp_path)

    analysis = client.post(
        "/api/v1/analyze",
        files={"file": ("../../unsafe.txt", "帐号测试".encode(), "text/plain")},
    )

    assert analysis.status_code == 200
    result = analysis.json()
    file_id = result["file_id"]
    assert result["filename"] == "unsafe.txt"
    assert (tmp_path / "compatibility" / file_id / "source.txt").read_text() == "帐号测试"

    exported = client.post(
        "/api/v1/export-original",
        json={
            "file_id": file_id,
            "filename": "../../unsafe.txt",
            "replacements": [
                {
                    "original": "帐号",
                    "suggestion": "账号",
                    "position": 0,
                    "end_position": 2,
                }
            ],
            "modified_text": "账号测试",
            "track_changes": False,
        },
    )

    assert exported.status_code == 200
    assert exported.content.decode() == "账号测试"
    assert "unsafe_%E4%BF%AE%E6%94%B9%E7%89%88_" in exported.headers["content-disposition"]
    assert exported.headers["content-disposition"].endswith(".txt")


def test_export_html_report_escapes_user_content(client: TestClient) -> None:
    response = client.post(
        "/api/v1/export",
        json={
            "filename": "<script>alert(1)</script>.txt",
            "stats": {"char_count": 1},
            "summary": {"total": 1},
            "issues": [
                {
                    "layer": "character",
                    "type": "typo",
                    "severity": "error",
                    "original": "<b>x</b>",
                    "suggestion": "y",
                    "description": "test",
                    "context": "context",
                }
            ],
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    html = response.text
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html


def test_docx_export_can_emit_word_track_changes(
    app: FastAPI,
    client: TestClient,
    tmp_path: Path,
) -> None:
    override_storage(app, tmp_path)
    source = BytesIO()
    document = Document()
    document.add_paragraph("帐号测试")
    document.save(source)

    analysis = client.post(
        "/api/v1/analyze",
        files={
            "file": (
                "source.docx",
                source.getvalue(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert analysis.status_code == 200

    exported = client.post(
        "/api/v1/export-original",
        json={
            "file_id": analysis.json()["file_id"],
            "filename": "source.docx",
            "replacements": [
                {
                    "original": "帐号",
                    "suggestion": "账号",
                    "position": 0,
                    "end_position": 2,
                }
            ],
            "modified_text": "账号测试",
            "track_changes": True,
        },
    )

    assert exported.status_code == 200
    with ZipFile(BytesIO(exported.content)) as archive:
        document_xml = archive.read("word/document.xml").decode()
    assert "<w:del " in document_xml
    assert "<w:ins " in document_xml
    assert "帐" in document_xml
    assert "账" in document_xml


def test_export_changes_only_the_selected_duplicate(
    app: FastAPI,
    client: TestClient,
    tmp_path: Path,
) -> None:
    override_storage(app, tmp_path)
    analysis = client.post(
        "/api/v1/analyze",
        files={"file": ("source.txt", "帐号 A 帐号 B".encode(), "text/plain")},
    )
    result = analysis.json()

    exported = client.post(
        "/api/v1/export-original",
        json={
            "file_id": result["file_id"],
            "filename": "source.txt",
            "replacements": [
                {
                    "original": "帐号",
                    "suggestion": "账号",
                    "position": 0,
                    "end_position": 2,
                }
            ],
            "modified_text": "账号 A 帐号 B",
            "track_changes": False,
        },
    )

    assert exported.status_code == 200
    assert exported.content.decode() == "账号 A 帐号 B"

    manually_edited = client.post(
        "/api/v1/export-original",
        json={
            "file_id": result["file_id"],
            "filename": "source.txt",
            "modified_text": "帐号 A 帐号（已核对） B",
            "track_changes": False,
        },
    )
    assert manually_edited.status_code == 200
    assert manually_edited.content.decode() == "帐号 A 帐号（已核对） B"


def test_docx_export_preserves_unaffected_run_formatting(
    app: FastAPI,
    client: TestClient,
    tmp_path: Path,
) -> None:
    override_storage(app, tmp_path)
    source = BytesIO()
    document = Document()
    paragraph = document.add_paragraph()
    paragraph.add_run("帐").bold = True
    paragraph.add_run("号测试").italic = True
    document.save(source)
    analysis = client.post(
        "/api/v1/analyze",
        files={
            "file": (
                "source.docx",
                source.getvalue(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )

    exported = client.post(
        "/api/v1/export-original",
        json={
            "file_id": analysis.json()["file_id"],
            "filename": "source.docx",
            "modified_text": "账号测试",
            "track_changes": False,
        },
    )

    assert exported.status_code == 200
    modified = Document(BytesIO(exported.content))
    runs = modified.paragraphs[0].runs
    assert runs[0].text == "账"
    assert runs[0].bold is True
    assert runs[1].text == "号测试"
    assert runs[1].italic is True


def test_docx_export_preserves_unaffected_inline_content(
    app: FastAPI,
    client: TestClient,
    tmp_path: Path,
) -> None:
    override_storage(app, tmp_path)
    source = BytesIO()
    document = Document()
    paragraph = document.add_paragraph()
    paragraph.add_run("A")
    paragraph.add_run().add_tab()
    paragraph.add_run("B")
    document.save(source)
    analysis = client.post(
        "/api/v1/analyze",
        files={
            "file": (
                "source.docx",
                source.getvalue(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )

    exported = client.post(
        "/api/v1/export-original",
        json={
            "file_id": analysis.json()["file_id"],
            "filename": "source.docx",
            "modified_text": "C\tB",
            "track_changes": False,
        },
    )

    assert exported.status_code == 200
    with ZipFile(BytesIO(exported.content)) as archive:
        document_xml = archive.read("word/document.xml").decode()
    assert "<w:tab/>" in document_xml
    assert Document(BytesIO(exported.content)).paragraphs[0].text == "C\tB"


def test_rtf_analysis_decodes_unicode_and_ansi_hex(
    app: FastAPI,
    client: TestClient,
    tmp_path: Path,
) -> None:
    override_storage(app, tmp_path)
    rtf = rb"{\rtf1\ansi\ansicpg936 Unicode: \u36134?\u21495? ANSI: \'d5\'ca\'ba\'c5}"
    analysis = client.post(
        "/api/v1/analyze",
        files={"file": ("source.rtf", rtf, "application/rtf")},
    )

    assert analysis.status_code == 200
    assert analysis.json()["text"] == "Unicode: 账号 ANSI: 帐号"


def test_rtf_export_keeps_offsets_after_repeated_paragraph_breaks(
    app: FastAPI,
    client: TestClient,
    tmp_path: Path,
) -> None:
    override_storage(app, tmp_path)
    source = rb"{\rtf1\ansi A\par\par\par B}"
    analysis = client.post(
        "/api/v1/analyze",
        files={"file": ("source.rtf", source, "application/rtf")},
    )
    result = analysis.json()
    assert result["text"] == "A\n\n\nB"

    exported = client.post(
        "/api/v1/export-original",
        json={
            "file_id": result["file_id"],
            "filename": "source.rtf",
            "modified_text": "A\n\n\nC",
            "track_changes": False,
        },
    )
    assert exported.status_code == 200
    reparsed = client.post(
        "/api/v1/analyze",
        files={"file": ("modified.rtf", exported.content, "application/rtf")},
    )
    assert reparsed.status_code == 200
    assert reparsed.json()["text"] == "A\n\n\nC"

    unicode_export = client.post(
        "/api/v1/export-original",
        json={
            "file_id": result["file_id"],
            "filename": "source.rtf",
            "modified_text": "A\n\n\nB\n😀",
            "track_changes": False,
        },
    )
    assert unicode_export.status_code == 200
    unicode_reparsed = client.post(
        "/api/v1/analyze",
        files={"file": ("unicode.rtf", unicode_export.content, "application/rtf")},
    )
    assert unicode_reparsed.status_code == 200
    assert unicode_reparsed.json()["text"] == "A\n\n\nB\n😀"


def test_pdf_export_resolves_duplicates_and_rejects_unsafe_insertions(
    app: FastAPI,
    client: TestClient,
    tmp_path: Path,
) -> None:
    import fitz

    override_storage(app, tmp_path)
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "word word")
    source = document.tobytes()
    document.close()
    analysis = client.post(
        "/api/v1/analyze",
        files={"file": ("source.pdf", source, "application/pdf")},
    )
    result = analysis.json()
    assert result["text"] == "word word"

    replaced = client.post(
        "/api/v1/export-original",
        json={
            "file_id": result["file_id"],
            "filename": "source.pdf",
            "modified_text": "term term",
            "track_changes": False,
        },
    )
    inserted = client.post(
        "/api/v1/export-original",
        json={
            "file_id": result["file_id"],
            "filename": "source.pdf",
            "modified_text": "word extra word",
            "track_changes": False,
        },
    )

    assert replaced.status_code == 200
    assert inserted.status_code == 400
    assert "does not support insertion-only edits" in inserted.json()["detail"]


def test_scenarios_and_formats_are_discoverable(client: TestClient) -> None:
    scenarios_response = client.get("/api/v1/scenarios")
    formats_response = client.get("/api/v1/formats")

    assert scenarios_response.status_code == 200
    assert {item["id"] for item in scenarios_response.json()["scenarios"]} == {
        "general",
        "academic",
        "business",
        "legal",
        "news",
        "technical",
    }
    assert {item["ext"] for item in formats_response.json()["formats"]} == {
        "txt",
        "docx",
        "doc",
        "pdf",
        "rtf",
        "md",
        "csv",
    }
