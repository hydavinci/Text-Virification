from __future__ import annotations

import io
import json
import os
import time
from collections.abc import Iterator

import httpx
import pymupdf
import pytest
from docx import Document

TERMINAL_FAILURE_STATUSES = {"failed", "partial", "expired"}


@pytest.fixture
def live_api_url() -> str:
    url = os.environ.get("LIVE_API_URL")
    if not url:
        pytest.skip(
            "LIVE_API_URL is not set; a live Compose API/worker with OCR runtime is required."
        )
    return url.rstrip("/")


def test_scanned_pdf_job_reports_real_ocr_and_reconstructs_docx(
    live_api_url: str,
) -> None:
    upload = httpx.post(
        f"{live_api_url}/api/v1/jobs",
        files={"file": ("scanned.pdf", _scanned_pdf(), "application/pdf")},
        timeout=60,
    )
    assert upload.status_code == 202, upload.text
    job_id = upload.json()["job_id"]

    events = list(_events_until_done(live_api_url, job_id))
    assert "ocr" in [event["stage"] for event in events]
    assert [event["progress"] for event in events] == sorted(
        event["progress"] for event in events
    )

    result_response = httpx.get(
        f"{live_api_url}/api/v1/jobs/{job_id}/result",
        timeout=30,
    )
    assert result_response.status_code == 200, result_response.text
    result = result_response.json()
    assert result["text"].strip()
    assert result["issues"]

    export_response = httpx.post(
        f"{live_api_url}/api/v1/jobs/{job_id}/exports",
        json={"format": "docx_reconstruction"},
        timeout=120,
    )
    assert export_response.status_code == 200, export_response.text
    artifact_id = export_response.json()["export_artifact_id"]
    download = httpx.get(
        f"{live_api_url}/api/v1/jobs/{job_id}/exports/{artifact_id}",
        timeout=60,
    )
    assert download.status_code == 200, download.text
    rebuilt = Document(io.BytesIO(download.content))
    assert any(paragraph.text.strip() for paragraph in rebuilt.paragraphs)

    wrong_job_download = httpx.get(
        f"{live_api_url}/api/v1/jobs/00000000-0000-0000-0000-000000000000/"
        f"exports/{artifact_id}",
        timeout=30,
    )
    assert wrong_job_download.status_code == 404


def _events_until_done(live_api_url: str, job_id: str) -> Iterator[dict[str, object]]:
    deadline = time.monotonic() + 120
    with httpx.stream(
        "GET",
        f"{live_api_url}/api/v1/jobs/{job_id}/events",
        timeout=130,
    ) as response:
        assert response.status_code == 200, response.text
        event_name = ""
        for line in response.iter_lines():
            if time.monotonic() > deadline:
                raise AssertionError("scanned PDF job did not complete within 120 seconds")
            if line.startswith("event:"):
                event_name = line.partition(":")[2].strip()
            elif line.startswith("data:"):
                payload = json.loads(line.partition(":")[2].strip())
                if event_name == "progress":
                    if payload["status"] in TERMINAL_FAILURE_STATUSES:
                        pytest.fail(f"job reached terminal failure: {payload}")
                    yield payload
                elif event_name == "done":
                    return
        raise AssertionError("SSE stream ended without a done event")


def _scanned_pdf() -> bytes:
    source = pymupdf.open()
    scan = pymupdf.open()
    try:
        page = source.new_page(width=600, height=240)
        page.insert_text(
            (40, 120),
            "Contact test@example.com for review",
            fontsize=28,
            fontname="helv",
        )
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
        scan_page = scan.new_page(width=600, height=240)
        scan_page.insert_image(scan_page.rect, stream=pixmap.tobytes("png"))
        return scan.tobytes()
    finally:
        source.close()
        scan.close()
