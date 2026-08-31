from collections import Counter
from datetime import UTC, datetime
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
    return _verification_result_with_issues(
        (issue,),
        document_id=document_id,
        verification_run_id=verification_run_id,
        text=text,
        summary=summary,
    )


def _verification_result_with_issues(
    issues: tuple[Issue, ...],
    *,
    document_id=None,
    verification_run_id=None,
    text: str,
    summary: VerificationSummary | None = None,
) -> VerificationResult:
    first_issue = issues[0]
    resolved_document_id = document_id or first_issue.document_id
    resolved_run_id = verification_run_id or first_issue.verification_run_id
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
        issues=issues,
        summary=summary
        or VerificationSummary(
            total=len(issues),
            by_type=dict(Counter(issue.type for issue in issues)),
            by_severity=dict(Counter(issue.severity.value for issue in issues)),
            by_rule=dict(Counter(issue.rule_id for issue in issues)),
            by_layer=dict(Counter(issue.layer for issue in issues)),
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


def _ad_extreme_issue(issue: Issue) -> Issue:
    return Issue(
        issue_id=uuid4(),
        document_id=issue.document_id,
        verification_run_id=issue.verification_run_id,
        block_id="p-0",
        page=None,
        start=2,
        end=4,
        block_start=2,
        block_end=4,
        original="领先",
        suggestion="较为领先",
        alternatives=[],
        type="ad_extreme",
        severity=IssueSeverity.ERROR,
        layer="security",
        message="广告法极限词",
        description="建议改为客观表述",
        rule_id="ad_extreme_words",
        rule_version="1",
        source="compatibility.analyzer",
        source_version="1",
        confidence=1.0,
        auto_fixable=True,
        context="帐号领先",
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


@pytest.mark.parametrize(
    ("field_name", "invalid_counts"),
    [
        ("by_type", {"typo": 1, "bogus": 1}),
        ("by_severity", {"warning": 1, "bogus": 1}),
        ("by_layer", {"character": 1, "bogus": 1}),
    ],
)
def test_verification_result_rejects_unknown_key_mixed_into_canonical_summary_bucket(
    field_name: str,
    invalid_counts: dict[str, int],
) -> None:
    first_issue = _canonical_issue()
    second_issue = _ad_extreme_issue(first_issue)
    summary_data = {
        "total": 2,
        "by_type": {"typo": 1, "ad_extreme": 1},
        "by_severity": {"warning": 1, "error": 1},
        "by_rule": {"cn_typo": 1, "ad_extreme_words": 1},
        "by_layer": {"character": 1, "security": 1},
    }
    summary_data[field_name] = invalid_counts

    with pytest.raises(ValidationError, match=f"summary {field_name} counts"):
        _verification_result_with_issues(
            (first_issue, second_issue),
            text="帐号领先",
            summary=VerificationSummary(**summary_data),
        )


def test_verification_result_accepts_explicit_legacy_localized_summary_labels() -> None:
    first_issue = _canonical_issue()
    second_issue = _ad_extreme_issue(first_issue)
    summary = VerificationSummary(
        total=2,
        by_type={"错别字": 1, "ad_extreme": 1},
        by_severity={"警告": 1, "错误": 1},
        by_rule={"cn_typo": 1, "ad_extreme_words": 1},
        by_layer={"字符层": 1, "合规/安全层": 1},
    )

    result = _verification_result_with_issues(
        (first_issue, second_issue),
        text="帐号领先",
        summary=summary,
    )

    assert result.summary == summary


def test_verification_summary_rejects_negative_bucket_counts() -> None:
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        VerificationSummary(total=0, by_type={"typo": -1})


def test_verification_summary_canonicalizes_nested_tuples_to_json_lists() -> None:
    summary = VerificationSummary.model_validate(
        {
            "total": 0,
            "llm_review": {
                "batches": (
                    {"issue_ids": ("first", "second")},
                    ("complete",),
                )
            },
        }
    )

    assert summary.llm_review == {
        "batches": [
            {"issue_ids": ["first", "second"]},
            ["complete"],
        ]
    }


@pytest.mark.parametrize(
    "invalid_value",
    [
        uuid4(),
        datetime(2026, 8, 31, tzinfo=UTC),
        object(),
        float("nan"),
        float("inf"),
        float("-inf"),
    ],
)
def test_verification_summary_rejects_non_json_review_metadata(
    invalid_value: object,
) -> None:
    with pytest.raises(ValidationError, match="JSON"):
        VerificationSummary(total=0, llm_review={"invalid": invalid_value})


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
