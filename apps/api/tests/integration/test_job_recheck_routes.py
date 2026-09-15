from __future__ import annotations

import json
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
            "ocr_language": "en",
            "enable_extended_rules": "true",
            "enable_semantic_discovery": "true",
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
    assert calls[0][2].ocr_language == "en"
    assert calls[0][2].enable_extended_rules is True
    assert calls[0][2].enable_semantic_discovery is True


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


@pytest.mark.parametrize("text", [
    "第一段\n\n第二段\n",
    "第一段\r\n第二段\r末尾 & + = % 😀\n",
])
def test_urlencoded_recheck_preserves_exact_text(client, app: FastAPI, text: str) -> None:
    from text_verification.api.dependencies import get_job_recheck_service

    class EchoService:
        def recheck(self, job_id, submitted_text, options):
            return JobRecheckResult(
                result=result().model_copy(update={"text": submitted_text}),
                grant="server-issued-opaque-grant",
            )

    app.dependency_overrides[get_job_recheck_service] = EchoService
    response = client.post(f"/api/v1/jobs/{JOB_ID}/recheck", data={"text": text})
    assert response.status_code == 200, response.text
    assert response.json()["result"]["text"] == text


def test_urlencoded_recheck_preserves_final_options_field(client, app: FastAPI) -> None:
    from text_verification.api.dependencies import get_job_recheck_service

    class EchoOptionsService:
        def recheck(self, job_id, submitted_text, options):
            return JobRecheckResult(
                result=result(),
                grant="|".join(options.banned_words),
            )

    app.dependency_overrides[get_job_recheck_service] = EchoOptionsService
    response = client.post(
        f"/api/v1/jobs/{JOB_ID}/recheck",
        data={"text": "正文", "banned_words": '["保留末尾字段"]'},
    )
    assert response.status_code == 200, response.text
    assert response.json()["grant"] == "保留末尾字段"


@pytest.mark.parametrize("text, expected_status", [
    ("中文\n", 200),
    ("中文\nx", 200),
    ("中文\nxx", 413),
])
def test_urlencoded_recheck_limits_decoded_utf8_bytes(
    client, app: FastAPI, tmp_path, text: str, expected_status: int,
) -> None:
    from text_verification.api.dependencies import get_job_recheck_service

    class EchoService:
        def recheck(self, job_id, submitted_text, options):
            return JobRecheckResult(result=result(), grant="opaque-grant")

    app.dependency_overrides[get_job_recheck_service] = EchoService
    app.dependency_overrides[get_settings] = lambda: Settings(
        app_env="test", storage_root=tmp_path, max_upload_bytes=8,
    )
    response = client.post(f"/api/v1/jobs/{JOB_ID}/recheck", data={"text": text})
    assert response.status_code == expected_status, response.text


def test_urlencoded_recheck_allows_encoded_options_with_near_limit_text(
    client, app: FastAPI, tmp_path,
) -> None:
    from text_verification.api.dependencies import get_job_recheck_service

    class EchoService:
        def recheck(self, job_id, submitted_text, options):
            return JobRecheckResult(
                result=result(),
                grant=str(len(options.banned_words)),
            )

    app.dependency_overrides[get_job_recheck_service] = EchoService
    app.dependency_overrides[get_settings] = lambda: Settings(
        app_env="test", storage_root=tmp_path, max_upload_bytes=1_000_000,
    )
    response = client.post(
        f"/api/v1/jobs/{JOB_ID}/recheck",
        data={
            "text": "中" * 333_333,
            "banned_words": json.dumps(
                [f"{index}" + "术" * 100 for index in range(100)],
                ensure_ascii=False,
            ),
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["grant"] == "100"
