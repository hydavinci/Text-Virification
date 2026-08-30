from uuid import uuid4

import pytest
from pydantic import ValidationError

from text_verification.config import Settings
from text_verification.domain.documents import FileType
from text_verification.domain.issues import Issue, IssueSeverity
from text_verification.domain.verification import (
    GlossaryTerm,
    Scenario,
    VerificationDegradation,
    VerificationExecutionMode,
    VerificationOptions,
    VerificationResult,
    VerificationStatistics,
    VerificationSummary,
)


def test_verification_options_keep_ad_extreme_disabled_by_default() -> None:
    options = VerificationOptions()

    assert options.enable_security is True
    assert options.enable_sensitive is True
    assert options.enable_ad_extreme is False


def test_verification_result_carries_canonical_ids_and_degradation_metadata() -> None:
    verification_run_id = uuid4()
    document_id = uuid4()
    issue = Issue(
        issue_id=uuid4(),
        document_id=document_id,
        verification_run_id=verification_run_id,
        block_id="p-1",
        page=1,
        start=0,
        end=2,
        block_start=0,
        block_end=2,
        original="帐号",
        suggestion="账号",
        alternatives=[],
        type="typo",
        severity=IssueSeverity.WARNING,
        layer="character",
        message="错别字",
        description="建议修正",
        rule_id="legacy.typo",
        rule_version="2026.08",
        source="legacy",
        source_version="1",
        confidence=0.9,
        auto_fixable=True,
        context="帐号测试",
    )

    result = VerificationResult(
        verification_run_id=verification_run_id,
        document_id=document_id,
        source_name="sample.pdf",
        file_type=FileType.PDF,
        scenario=Scenario.TECHNICAL,
        text="帐号测试",
        stats=VerificationStatistics(
            char_count=4,
            char_count_no_space=4,
            line_count=1,
            paragraph_count=1,
            language="zh",
            primary_count=4,
            primary_label="汉字",
        ),
        issues=(issue,),
        summary=VerificationSummary(
            total=1,
            by_type={"typo": 1},
            by_severity={"warning": 1},
            by_rule={"legacy.typo": 1},
            by_layer={"character": 1},
        ),
        execution_mode=VerificationExecutionMode.RULES_WITH_OPTIONAL_LLM,
        degradation=VerificationDegradation(
            is_degraded=True,
            reasons=("llm_review_disabled",),
        ),
    )

    assert result.verification_run_id == verification_run_id
    assert result.document_id == document_id
    assert result.issues[0].issue_id == issue.issue_id
    assert result.degradation.is_degraded is True
    assert result.degradation.reasons == ("llm_review_disabled",)


def test_verification_options_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        VerificationOptions(
            custom_glossary=(GlossaryTerm(original="AI", standard="人工智能"),),
            unexpected=True,
        )


def test_settings_expose_typed_llm_fields_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "secret-key")
    monkeypatch.setenv("LLM_API_BASE", "https://example.test/v1")
    monkeypatch.setenv("LLM_MODEL", "gpt-4.1-mini")
    monkeypatch.setenv("LLM_MAX_REVIEW", "41")
    monkeypatch.setenv("LLM_CONTEXT_RADIUS", "52")
    monkeypatch.setenv("LLM_TIMEOUT", "61.5")
    monkeypatch.setenv("LLM_JSON_MODE", "1")

    settings = Settings()

    assert settings.llm_api_key == "secret-key"
    assert settings.llm_api_base == "https://example.test/v1"
    assert settings.llm_model == "gpt-4.1-mini"
    assert settings.llm_max_review == 41
    assert settings.llm_context_radius == 52
    assert settings.llm_timeout == 61.5
    assert settings.llm_json_mode is True


def test_settings_reject_non_positive_llm_limits() -> None:
    with pytest.raises(ValidationError, match="llm_max_review"):
        Settings(llm_max_review=0)
