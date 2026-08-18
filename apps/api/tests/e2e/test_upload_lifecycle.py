import os
import time
from collections.abc import Callable
from typing import Any

import httpx
import pytest

TERMINAL_FAILURE_STATUSES = {"failed", "partial", "expired"}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
POLL_INTERVAL_SECONDS = 0.25
DEFAULT_TIMEOUT_SECONDS = 60


@pytest.fixture
def live_api_url() -> str:
    url = os.environ.get("LIVE_API_URL")
    if not url:
        pytest.skip("LIVE_API_URL is not set; the live Compose stack is required.")
    return url.rstrip("/")


def create_txt_job(
    live_api_url: str,
    *,
    source_name: str,
    content: str,
    scenario: str | None = None,
    enabled_categories: list[str] | None = None,
) -> dict[str, Any]:
    files: list[tuple[str, tuple[str | None, bytes | str, str | None]]] = [
        ("file", (source_name, content.encode("utf-8"), "text/plain"))
    ]

    if scenario is not None:
        files.append(("scenario", (None, scenario, None)))

    for category in enabled_categories or []:
        files.append(("enabled_categories", (None, category, None)))

    response = httpx.post(f"{live_api_url}/api/v1/jobs", files=files, timeout=30)
    assert response.status_code == 202, response.text
    return response.json()


def get_json(
    live_api_url: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: int = 10,
) -> dict[str, Any]:
    response = httpx.get(f"{live_api_url}{path}", params=params, timeout=timeout)
    assert response.status_code == 200, response.text
    return response.json()


def poll_until(
    fetch: Callable[[], dict[str, Any]],
    *,
    description: str,
    is_complete: Callable[[dict[str, Any]], bool],
    terminal_statuses: set[str],
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_payload: dict[str, Any] | None = None

    while time.monotonic() < deadline:
        last_payload = fetch()
        status = str(last_payload.get("status", ""))

        if is_complete(last_payload):
            return last_payload
        if status in terminal_statuses:
            pytest.fail(f"{description} reached terminal status {status}: {last_payload}")

        time.sleep(POLL_INTERVAL_SECONDS)

    raise AssertionError(f"{description} did not complete within {timeout_seconds} seconds")


def test_txt_upload_reaches_completed_state(live_api_url: str) -> None:
    created = create_txt_job(
        live_api_url,
        source_name="sample.txt",
        content="需要检查",
    )
    job_id = created["job_id"]

    job = poll_until(
        lambda: get_json(live_api_url, f"/api/v1/jobs/{job_id}"),
        description=f"job {job_id}",
        is_complete=lambda payload: payload["status"] == "completed",
        terminal_statuses=TERMINAL_FAILURE_STATUSES,
    )

    assert job["progress"] == 100


def test_exact_maximum_txt_upload_is_accepted_through_web_ingress(
    live_api_url: str,
) -> None:
    response = httpx.post(
        f"{live_api_url}/api/v1/jobs",
        files={"file": ("boundary.txt", b"a" * MAX_UPLOAD_BYTES, "text/plain")},
        timeout=60,
    )

    assert response.status_code == 202, response.text


def test_txt_upload_options_review_and_html_report_download(
    live_api_url: str,
) -> None:
    created = create_txt_job(
        live_api_url,
        source_name="sample.txt",
        content=(
            "祕密项目需要尽快完成。\n"
            "联系电话 : 12345。\n"
            "总之首先，我们非常非常看好这个方案，也绝对领先。"
        ),
        scenario="general",
        enabled_categories=[
            "character",
            "sentence",
            "format",
            "discourse",
            "security",
        ],
    )
    job_id = created["job_id"]

    assert created["scenario"] == "general"
    assert created["enabled_categories"] == [
        "character",
        "sentence",
        "format",
        "discourse",
        "security",
    ]

    poll_until(
        lambda: get_json(live_api_url, f"/api/v1/jobs/{job_id}"),
        description=f"job {job_id}",
        is_complete=lambda payload: payload["status"] == "completed",
        terminal_statuses=TERMINAL_FAILURE_STATUSES,
    )

    summary = get_json(live_api_url, f"/api/v1/jobs/{job_id}/summary")
    assert summary["status"] == "completed"
    assert summary["total_issues"] >= 4

    first_document_page = get_json(
        live_api_url,
        f"/api/v1/jobs/{job_id}/document",
        params={"limit": 1},
    )
    assert first_document_page["blocks"]
    assert first_document_page["total_blocks"] >= 1
    assert first_document_page["blocks"][0]["text"].startswith("祕密项目")

    first_issue_page = get_json(
        live_api_url,
        f"/api/v1/jobs/{job_id}/issues",
        params={"limit": 1},
    )
    assert first_issue_page["items"]
    assert first_issue_page["next_cursor"] is not None

    second_issue_page = get_json(
        live_api_url,
        f"/api/v1/jobs/{job_id}/issues",
        params={"limit": 1, "cursor": first_issue_page["next_cursor"]},
    )
    assert second_issue_page["items"]

    first_issue = first_issue_page["items"][0]
    assert first_issue["auto_fixable"] is True

    decision_response = httpx.put(
        f"{live_api_url}/api/v1/jobs/{job_id}/decisions",
        json={
            "decisions": [
                {
                    "issue_id": first_issue["issue_id"],
                    "issue_version": first_issue["document_version"],
                    "action": "accepted",
                    "replacement": None,
                }
            ]
        },
        timeout=30,
    )
    assert decision_response.status_code == 200, decision_response.text
    assert decision_response.json()["outcomes"][0]["status"] == "applied"

    updated_summary = get_json(live_api_url, f"/api/v1/jobs/{job_id}/summary")
    assert updated_summary["by_decision"]["accepted"] == 1

    export_response = httpx.post(
        f"{live_api_url}/api/v1/jobs/{job_id}/exports",
        json={"type": "html_report"},
        timeout=30,
    )
    assert export_response.status_code == 202, export_response.text
    export_id = export_response.json()["export_id"]

    completed_export = poll_until(
        lambda: get_json(live_api_url, f"/api/v1/jobs/{job_id}/exports/{export_id}"),
        description=f"export {export_id}",
        is_complete=lambda payload: payload["status"] == "completed",
        terminal_statuses={"failed"},
    )
    assert completed_export["file_name"] == "report.html"

    download_response = httpx.get(
        f"{live_api_url}/api/v1/jobs/{job_id}/exports/{export_id}/download",
        timeout=30,
    )
    assert download_response.status_code == 200, download_response.text

    html = download_response.content.decode("utf-8")
    assert "问题报告" in html
    assert "sample.txt" in html
    assert "启用分类" in html
    assert "祕密" in html
