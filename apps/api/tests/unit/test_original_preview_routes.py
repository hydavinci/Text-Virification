from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from text_verification.api.dependencies import get_db_session, get_job_storage
from text_verification.api.routes import jobs
from text_verification.domain.verification import VerificationResult
from text_verification.infrastructure.storage import JobStorage
from text_verification.infrastructure.verification_repository import (
    JobResultSnapshot,
    JobResultState,
)


@pytest.mark.parametrize(
    ("state", "status_code"),
    [(JobResultState.READY, 200), (JobResultState.EXPIRED, 410),
     (JobResultState.MISSING, 404), (JobResultState.PENDING, 409)],
)
@pytest.mark.parametrize("layout", [False, True])
def test_preview_honors_result_lifecycle(
    app: FastAPI, client: TestClient, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch, state: JobResultState, status_code: int,
    layout: bool,
) -> None:
    job_id = uuid4()
    data = b"%PDF-1.7\noriginal"
    storage = JobStorage(tmp_path, 1024)
    storage.save_bytes(job_id, "original.pdf", data)
    result = VerificationResult.model_validate({
        "document_id": job_id, "verification_run_id": uuid4(),
        "source_version": f"sha256:{hashlib.sha256(data).hexdigest()}",
        "source_name": "original.pdf", "file_type": "pdf", "scenario": "general",
        "text": "", "blocks": [], "issues": [],
        "parser_name": "test", "parser_version": "1",
        "stats": {"char_count": 0, "char_count_no_space": 0, "line_count": 0,
                  "paragraph_count": 0, "language": "en", "primary_count": 0,
                  "primary_label": "characters"},
        "summary": {"total": 0}, "execution_mode": "asynchronous",
        "analysis_mode": "local_only",
    })

    class Repository:
        def read_result_snapshot(self, requested_id):
            assert requested_id == job_id
            return JobResultSnapshot(state, result if state is JobResultState.READY else None)

        def rollback(self):
            pass

    monkeypatch.setattr(jobs, "VERIFICATION_REPOSITORY_FACTORY", lambda _: Repository())
    app.dependency_overrides[get_db_session] = lambda: None
    app.dependency_overrides[get_job_storage] = lambda: storage
    if layout:
        from text_verification.api.routes import original_preview
        from text_verification.domain.review_layout import ReviewLayout

        monkeypatch.setattr(
            original_preview, "build_review_preview",
            lambda *_: ReviewLayout(pages=[], revision_applied=True), raising=False,
        )
        response = client.post(
            f"/api/v1/jobs/{job_id}/preview/layout",
            json={"source_version": result.source_version, "text": result.text},
        )
    else:
        response = client.get(f"/api/v1/jobs/{job_id}/preview")
    assert response.status_code == status_code
    if status_code == 200:
        if layout:
            assert response.json()["revision_applied"] is True
        else:
            assert response.content == data
            assert response.headers["content-type"] == "application/pdf"
        assert response.headers["cache-control"] == "no-store"
    else:
        assert data not in response.content
