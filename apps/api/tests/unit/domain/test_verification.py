from uuid import uuid4

import pytest
from pydantic import ValidationError

from text_verification.config import Settings
from text_verification.domain.documents import FileType
from text_verification.domain.issues import Issue, IssueSeverity
from text_verification.domain.verification import (
    GlossaryTerm,
    Scenario,
    VerificationAnalysisMode,
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
        source_version="sha256:sample",
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
        execution_mode=VerificationExecutionMode.SYNCHRONOUS,
        analysis_mode=VerificationAnalysisMode.LOCAL_ONLY,
        degradation=VerificationDegradation(),
    )

    assert result.verification_run_id == verification_run_id
    assert result.document_id == document_id
    assert result.issues[0].issue_id == issue.issue_id
    assert result.dictionary_versions == {}
    assert result.degradation.is_degraded is False
    assert result.degradation.reasons == ()


def _verification_result(
    issue: Issue,
    *,
    document_id=None,
    verification_run_id=None,
    text: str = "帐号测试",
    summary: VerificationSummary | None = None,
) -> VerificationResult:
    resolved_document_id = document_id or issue.document_id
    resolved_run_id = verification_run_id or issue.verification_run_id
    return VerificationResult(
        verification_run_id=resolved_run_id,
        document_id=resolved_document_id,
        source_version="sha256:sample",
        source_name="sample.txt",
        file_type=FileType.TXT,
        scenario=Scenario.GENERAL,
        text=text,
        stats=VerificationStatistics(
            char_count=len(text),
            char_count_no_space=len(text),
            line_count=1,
            paragraph_count=1,
            language="zh",
            primary_count=len(text),
            primary_label="总字数",
        ),
        issues=(issue,),
        summary=summary
        or VerificationSummary(
            total=1,
            by_type={issue.type: 1},
            by_severity={issue.severity.value: 1},
            by_rule={issue.rule_id: 1},
            by_layer={issue.layer: 1},
        ),
        execution_mode=VerificationExecutionMode.SYNCHRONOUS,
        analysis_mode=VerificationAnalysisMode.LOCAL_ONLY,
    )


def _canonical_issue() -> Issue:
    document_id = uuid4()
    verification_run_id = uuid4()
    return Issue(
        issue_id=uuid4(),
        document_id=document_id,
        verification_run_id=verification_run_id,
        block_id="p-0",
        page=None,
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
        rule_id="cn_typo",
        rule_version="1",
        source="compatibility.analyzer",
        source_version="1",
        confidence=0.8,
        auto_fixable=True,
        context="帐号测试",
    )


def test_verification_result_rejects_issue_from_another_document() -> None:
    with pytest.raises(ValidationError, match="document ownership"):
        _verification_result(_canonical_issue(), document_id=uuid4())


def test_verification_result_rejects_issue_from_another_run() -> None:
    with pytest.raises(ValidationError, match="run ownership"):
        _verification_result(_canonical_issue(), verification_run_id=uuid4())


def test_verification_result_rejects_issue_original_not_matching_document_text() -> None:
    with pytest.raises(ValidationError, match="original text"):
        _verification_result(_canonical_issue(), text="账号测试")


@pytest.mark.parametrize(
    "summary",
    [
        VerificationSummary(
            total=2,
            by_type={"typo": 1},
            by_severity={"warning": 1},
            by_rule={"cn_typo": 1},
            by_layer={"character": 1},
        ),
        VerificationSummary(
            total=1,
            by_type={"typo": 0},
            by_severity={"warning": 1},
            by_rule={"cn_typo": 1},
            by_layer={"character": 1},
        ),
        VerificationSummary(
            total=1,
            by_type={"typo": 1},
            by_severity={"warning": 1},
            by_rule={"other_rule": 1},
            by_layer={"character": 1},
        ),
    ],
)
def test_verification_result_rejects_summary_inconsistent_with_issues(
    summary: VerificationSummary,
) -> None:
    with pytest.raises(ValidationError, match="summary"):
        _verification_result(_canonical_issue(), summary=summary)


def test_verification_summary_rejects_negative_bucket_counts() -> None:
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        VerificationSummary(total=0, by_type={"typo": -1})


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
