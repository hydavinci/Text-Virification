from __future__ import annotations

from uuid import UUID

import pytest
from fastapi import FastAPI

from text_verification.application.job_recheck import JobRecheckResult
from text_verification.config import Settings, get_settings
from text_verification.domain.documents import FileType
from text_verification.domain.verification import (
    Scenario,
    VerificationAnalysisMode,
    VerificationDegradation,
    VerificationExecutionMode,
    VerificationResult,
    VerificationStatistics,
    VerificationSummary,
)

JOB_ID = UUID("10000000-0000-4000-8000-000000000001")
RESULT_DOCUMENT_ID = UUID("20000000-0000-4000-8000-000000000002")
RESULT_RUN_ID = UUID("30000000-0000-4000-8000-000000000003")


def result() -> VerificationResult:
    return VerificationResult(
        verification_run_id=RESULT_RUN_ID,
        document_id=RESULT_DOCUMENT_ID,
        source_version="sha256:" + "b" * 64,
        source_name="直接输入文本",
        file_type=FileType.TXT,
        scenario=Scenario.GENERAL,
        text="重新检查文本",
        blocks=(),
        parser_name="direct-text",
        parser_version="1",
        stats=VerificationStatistics(
            char_count=6,
            char_count_no_space=6,
            line_count=1,
            paragraph_count=1,
            language="zh",
            primary_count=6,
            primary_label="总字数",
        ),
        issues=(),
        summary=VerificationSummary(total=0),
        execution_mode=VerificationExecutionMode.SYNCHRONOUS,
        analysis_mode=VerificationAnalysisMode.LOCAL_ONLY,
        degradation=VerificationDegradation(),
    )


def test_job_bound_recheck_returns_fresh_result_and_opaque_grant(
    client,
    app: FastAPI,
) -> None:
    from text_verification.api.dependencies import get_job_recheck_service

    calls: list[tuple[UUID, str, object]] = []

    class FakeService:
        def recheck(self, job_id, text, options):
            calls.append((job_id, text, options))
            return JobRecheckResult(
                result=result(),
                grant="server-issued-opaque-grant",
            )

    app.dependency_overrides[get_job_recheck_service] = FakeService

    response = client.post(
        f"/api/v1/jobs/{JOB_ID}/recheck",
        data={
            "text": "重新检查文本",
            "scenario": "general",
            "enable_security": "true",
            "enable_sensitive": "false",
            "enable_ad_extreme": "true",
            "custom_glossary": "[]",
            "banned_words": "[]",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["grant"] == "server-issued-opaque-grant"
    assert payload["result"]["document_id"] == str(RESULT_DOCUMENT_ID)
    assert payload["result"]["verification_run_id"] == str(RESULT_RUN_ID)
    assert payload["result"]["text"] == "重新检查文本"
    assert payload["result"]["success"] is True
    assert calls[0][0:2] == (JOB_ID, "重新检查文本")


def test_recheck_accepts_multipart_text_above_framework_default_when_configured(
    client,
    app: FastAPI,
    tmp_path,
) -> None:
    from text_verification.api.dependencies import get_job_recheck_service

    text = "a" * (1024 * 1024 + 1)
    calls: list[int] = []

    class FakeService:
        def recheck(self, job_id, submitted_text, options):
            del job_id, options
            calls.append(len(submitted_text))
            return JobRecheckResult(result=result(), grant="opaque-grant")

    app.dependency_overrides[get_settings] = lambda: Settings(
        app_env="test",
        storage_root=tmp_path,
        max_upload_bytes=len(text),
    )
    app.dependency_overrides[get_job_recheck_service] = FakeService

    response = client.post(
        f"/api/v1/jobs/{JOB_ID}/recheck",
        files={"text": (None, text)},
    )

    assert response.status_code == 200
    assert calls == [len(text)]


def test_recheck_multipart_text_limit_is_inclusive(
    client,
    app: FastAPI,
    tmp_path,
) -> None:
    from text_verification.api.dependencies import get_job_recheck_service

    calls: list[str] = []

    class FakeService:
        def recheck(self, job_id, submitted_text, options):
            del job_id, options
            calls.append(submitted_text)
            return JobRecheckResult(result=result(), grant="opaque-grant")

    app.dependency_overrides[get_settings] = lambda: Settings(
        app_env="test",
        storage_root=tmp_path,
        max_upload_bytes=8,
    )
    app.dependency_overrides[get_job_recheck_service] = FakeService

    accepted = client.post(
        f"/api/v1/jobs/{JOB_ID}/recheck",
        files={"text": (None, "12345678")},
    )
    rejected = client.post(
        f"/api/v1/jobs/{JOB_ID}/recheck",
        files={"text": (None, "123456789")},
    )

    assert accepted.status_code == 200
    assert rejected.status_code == 413
    assert calls == ["12345678"]


def test_recheck_validation_errors_do_not_reflect_form_secrets(
    client,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "recheck-form-secret-never-reflect"

    response = client.post(
        f"/api/v1/jobs/{JOB_ID}/recheck",
        files={
            "text": (None, "text"),
            "scenario": (None, secret),
        },
    )

    assert response.status_code == 422
    assert secret not in response.text
    assert secret not in caplog.text
