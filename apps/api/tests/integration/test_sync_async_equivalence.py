from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from text_verification.application import build_default_verification_pipeline
from text_verification.config import Settings
from text_verification.domain.jobs import (
    TERMINAL_STATUSES,
    JobRead,
    JobStatus,
    TerminalJobStateError,
)
from text_verification.domain.verification import VerificationResult
from text_verification.infrastructure.storage import JobStorage
from text_verification.workers.pipeline import PipelineRunner

SAMPLE = "帐号包含 test@example.com。"


class EquivalenceJobRepository:
    def __init__(self, job: JobRead) -> None:
        self._job = job

    def get_job(self, job_id: UUID) -> JobRead | None:
        return self._job if self._job.job_id == job_id else None

    def transition(
        self,
        job_id: UUID,
        status: JobStatus,
        progress: int,
        message: str,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        del message
        if self._job.job_id != job_id:
            raise LookupError(job_id)
        if self._job.status in TERMINAL_STATUSES:
            raise TerminalJobStateError(
                job_id=job_id,
                current_status=self._job.status,
                target_status=status,
            )
        self._job = self._job.model_copy(
            update={
                "status": status,
                "progress": progress,
                "error_code": error_code,
                "error_message": error_message,
            }
        )

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


class EquivalenceVerificationRepository:
    def __init__(self) -> None:
        self._results: dict[UUID, VerificationResult] = {}

    def save_result(self, job_id: UUID, result: VerificationResult) -> None:
        self._results[job_id] = result

    def get_result_for_job(self, job_id: UUID) -> VerificationResult | None:
        return self._results.get(job_id)

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


def test_sync_and_async_results_have_equivalent_canonical_semantics(
    app: FastAPI,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from text_verification.api.dependencies import get_db_session
    from text_verification.api.routes import jobs as job_routes

    settings = Settings(storage_root=tmp_path / "jobs", llm_api_key="")
    app.state.verification_pipeline = build_default_verification_pipeline(settings)
    storage = JobStorage(settings.storage_root, settings.max_upload_bytes)
    job_id = uuid4()
    stored = storage.save_bytes(job_id, "sample.txt", SAMPLE.encode("utf-8"))
    created_at = datetime.now(UTC)
    job_repository = EquivalenceJobRepository(
        JobRead(
            job_id=job_id,
            source_name=stored.original_name,
            file_type=stored.file_type,
            size_bytes=stored.size_bytes,
            status=JobStatus.QUEUED,
            progress=0,
            created_at=created_at,
            expires_at=created_at + timedelta(hours=24),
        )
    )
    result_repository = EquivalenceVerificationRepository()
    runner = PipelineRunner(
        job_repository,
        result_repository,
        storage,
        build_default_verification_pipeline(settings),
    )

    runner.run(job_id)
    monkeypatch.setattr(job_routes, "REPOSITORY_FACTORY", lambda session: job_repository)
    monkeypatch.setattr(
        job_routes,
        "VERIFICATION_REPOSITORY_FACTORY",
        lambda session: result_repository,
        raising=False,
    )
    app.dependency_overrides[get_db_session] = lambda: object()

    sync_response = client.post("/api/v1/analyze", data={"text": SAMPLE})
    async_response = client.get(f"/api/v1/jobs/{job_id}/result")

    assert sync_response.status_code == 200
    assert async_response.status_code == 200
    assert job_repository.get_job(job_id).status is JobStatus.COMPLETED
    assert _normalize_sync(sync_response.json()) == _normalize_async(async_response.json())


def _normalize_sync(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_version": payload["source_version"],
        "scenario": payload["scenario"],
        "text": payload["text"],
        "stats": payload["stats"],
        "issues": [_normalize_sync_issue(issue) for issue in payload["issues"]],
        "summary": payload["summary"],
        "analysis_mode": payload["analysis_mode"],
        "dictionary_versions": payload["dictionary_versions"],
        "degradation": payload["degradation"],
    }


def _normalize_async(payload: dict[str, Any]) -> dict[str, Any]:
    summary = dict(payload["summary"])
    if summary.get("llm_review") is None:
        summary.pop("llm_review", None)
    return {
        "source_version": payload["source_version"],
        "scenario": payload["scenario"],
        "text": payload["text"],
        "stats": payload["stats"],
        "issues": [_normalize_async_issue(issue) for issue in payload["issues"]],
        "summary": summary,
        "analysis_mode": payload["analysis_mode"],
        "dictionary_versions": payload["dictionary_versions"],
        "degradation": payload["degradation"],
    }


def _normalize_sync_issue(issue: dict[str, Any]) -> dict[str, Any]:
    return {
        "issue_id": issue["issue_id"],
        "page": issue["page"],
        "start": issue["position"],
        "end": issue["end_position"],
        "block_start": issue["block_start"],
        "block_end": issue["block_end"],
        "original": issue["original"],
        "suggestion": issue["suggestion"],
        "alternatives": issue["alternatives"] or [],
        "type": issue["type"],
        "severity": issue["severity"],
        "layer": issue["layer"],
        "message": issue["message"],
        "description": issue["description"],
        "rule_id": issue["rule_id"],
        "rule_version": issue["rule_version"],
        "source": issue["source"],
        "source_version": issue["source_version"],
        "confidence": issue["confidence"],
        "auto_fixable": issue["auto_fixable"],
        "context": issue["context"],
        "review": issue["review"] or None,
        "review_reason": issue["review_reason"] or None,
    }


def _normalize_async_issue(issue: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in issue.items()
        if key not in {"block_id", "document_id", "verification_run_id"}
    }
