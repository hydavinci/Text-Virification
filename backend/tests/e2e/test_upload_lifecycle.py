import os
import time

import httpx
import pytest

TERMINAL_FAILURE_STATUSES = {"failed", "partial", "expired"}


@pytest.fixture
def live_api_url() -> str:
    url = os.environ.get("LIVE_API_URL")
    if not url:
        pytest.skip("LIVE_API_URL is not set; the live Compose stack is required.")
    return url.rstrip("/")


def test_txt_upload_reaches_completed_state(live_api_url: str) -> None:
    response = httpx.post(
        f"{live_api_url}/api/v1/jobs",
        files={"file": ("sample.txt", "需要检查".encode(), "text/plain")},
        timeout=30,
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        response = httpx.get(f"{live_api_url}/api/v1/jobs/{job_id}", timeout=10)
        assert response.status_code == 200, response.text
        job = response.json()
        status = job["status"]

        if status == "completed":
            assert job["progress"] == 100
            return
        if status in TERMINAL_FAILURE_STATUSES:
            pytest.fail(f"job reached terminal status {status}: {job}")

        time.sleep(0.25)

    raise AssertionError("job did not complete within 30 seconds")
