import logging
from types import SimpleNamespace

import httpx
import pytest
from openai import APITimeoutError, AuthenticationError

from text_verification.compatibility import llm_review
from text_verification.compatibility.analyzer import Issue
from text_verification.config import Settings


def _review_candidate() -> Issue:
    return Issue(
        type="punctuation",
        severity="warning",
        original="，，",
        suggestion="，",
        position=2,
        end_position=4,
        context="中文，，文本",
        description="连续重复标点符号",
        rule_id="repeat_punct",
        layer="format",
    )


def test_json_object_review_envelope_is_supported() -> None:
    assert llm_review._parse_response(
        '{"verdicts":[{"id":0,"verdict":"real","reason":"valid"}]}', 1,
    ) == {0: ("real", "valid")}


@pytest.mark.parametrize("response", [
    "[]",
    '[{"id":0,"verdict":"real"},{"id":0,"verdict":"false_positive"}]',
    '[{"id":true,"verdict":"real"}]',
    '[{"id":0.5,"verdict":"real"}]',
    '[{"id":0,"verdict":"unexpected"}]',
])
def test_incomplete_or_invalid_review_never_silently_deletes_findings(response) -> None:
    with pytest.raises(llm_review.InvalidReviewResponseError):
        llm_review._parse_response(response, 1)


def test_review_routes_actual_uncertainty_not_severity() -> None:
    assert llm_review._needs_review(SimpleNamespace(
        type="grammar", severity="error", confidence=0.7,
    ))
    assert not llm_review._needs_review(SimpleNamespace(
        type="grammar", severity="info", confidence=0.98,
    ))
    assert not llm_review._needs_review(SimpleNamespace(
        type="banned_word", severity="info", confidence=0.4,
    ))


@pytest.mark.parametrize("confidence,expected", [(0.55, True), (0.8, True), (0.95, False)])
def test_uncertain_dictionary_typos_are_reviewable_but_curated_typos_are_not(
    confidence, expected,
) -> None:
    assert llm_review._needs_review(SimpleNamespace(
        type="typo", severity="error", confidence=confidence,
    )) is expected


def test_missing_confidence_uses_neutral_heuristic_not_severity() -> None:
    assert llm_review._needs_review(SimpleNamespace(
        type="grammar", severity="error", confidence=None,
    ))
    assert llm_review._needs_review(SimpleNamespace(
        type="grammar", severity="info", confidence=None,
    ))


def test_review_sampling_spreads_budget_across_categories_and_positions() -> None:
    candidates = [
        (i, SimpleNamespace(type="grammar" if i < 90 else "expression", position=i * 10))
        for i in range(100)
    ]
    sampled = llm_review._sample_candidates(candidates, 6)
    assert len(sampled) == 6
    assert {issue.type for _, issue in sampled} == {"grammar", "expression"}
    assert sampled[0][1].position == 0
    assert sampled[-1][1].position == 990


def test_review_uncertainty_sets_explicit_confidence_for_legacy_findings(monkeypatch) -> None:
    class Client:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=self)

        def create(self, **kwargs):
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content='{"verdicts":[{"id":0,"verdict":"uncertain"}]}'),
                finish_reason="stop",
            )])

    monkeypatch.setattr(llm_review, "OpenAI", Client)
    issue = _review_candidate()
    issue.confidence = None
    reviewed, _ = llm_review.review_issues(
        Settings(_env_file=None, llm_api_key="test-only"), "中文，，文本", [issue],
    )
    assert reviewed[0].confidence == 0.55


def test_review_rejects_duplicate_json_fields() -> None:
    with pytest.raises(llm_review.InvalidReviewResponseError):
        llm_review._parse_response(
            '[{"id":0,"verdict":"real","verdict":"false_positive"}]', 1,
        )


def test_review_rejects_truncated_provider_response_even_with_valid_json() -> None:
    response = SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content='{"verdicts": []}'), finish_reason="length",
    )])
    with pytest.raises(llm_review.InvalidReviewResponseError):
        llm_review._response_content(response)


def test_review_cannot_remove_partial_glossary_or_compliance_hits() -> None:
    from text_verification.domain.ports import CheckContext

    assert llm_review._constrained_issue(
        SimpleNamespace(original="ro", position=1, end_position=3),
        CheckContext(custom_glossary=({"original": "Product", "standard": "ProductName"},)),
        "Product",
    )
    assert not llm_review._needs_review(SimpleNamespace(
        type="ad_extreme", layer="security", severity="warning", confidence=0.5,
    ))


def test_provider_exception_is_logged_but_not_exposed_in_review_metadata(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FailingCompletions:
        def create(self, **kwargs: object) -> object:
            del kwargs
            request = httpx.Request("POST", "https://provider.invalid/review")
            raise AuthenticationError(
                "provider secret endpoint detail",
                response=httpx.Response(401, request=request),
                body={"error": "invalid credentials"},
            )

    class FailingOpenAI:
        def __init__(self, **kwargs: object) -> None:
            del kwargs
            self.chat = type("Chat", (), {"completions": FailingCompletions()})()

    monkeypatch.setattr(llm_review, "OpenAI", FailingOpenAI)

    with caplog.at_level(logging.ERROR, logger=llm_review.__name__):
        issues, stats = llm_review.review_issues(
            Settings(llm_api_key="configured"),
            "中文，，文本",
            [_review_candidate()],
        )

    assert len(issues) == 1
    assert stats["failed"] is True
    assert stats["failure_code"] == "llm_provider_error"
    assert stats["retryable"] is False
    assert stats["reason"] == "大模型调用失败，已回退纯规则结果"
    assert "provider secret" not in repr(stats)
    record = caplog.records[-1]
    assert record.getMessage() == "llm_review_provider_failed"
    assert record.exc_info is None
    assert record.provider_error_type == "AuthenticationError"
    assert record.provider_status == 401
    assert record.retryable is False
    assert "provider secret endpoint detail" not in caplog.text
    assert "invalid credentials" not in caplog.text
    assert "Traceback" not in caplog.text


def test_transient_provider_failure_is_classified_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingCompletions:
        def create(self, **kwargs: object) -> object:
            del kwargs
            raise APITimeoutError(
                request=httpx.Request("POST", "https://provider.invalid/review")
            )

    class FailingOpenAI:
        def __init__(self, **kwargs: object) -> None:
            del kwargs
            self.chat = type("Chat", (), {"completions": FailingCompletions()})()

    monkeypatch.setattr(llm_review, "OpenAI", FailingOpenAI)

    issues, stats = llm_review.review_issues(
        Settings(llm_api_key="configured"),
        "中文，，文本",
        [_review_candidate()],
    )

    assert len(issues) == 1
    assert stats["failed"] is True
    assert stats["failure_code"] == "llm_provider_error"
    assert stats["retryable"] is True


def test_untyped_provider_programming_error_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingCompletions:
        def create(self, **kwargs: object) -> object:
            del kwargs
            raise RuntimeError("provider adapter programming defect")

    class FailingOpenAI:
        def __init__(self, **kwargs: object) -> None:
            del kwargs
            self.chat = type("Chat", (), {"completions": FailingCompletions()})()

    monkeypatch.setattr(llm_review, "OpenAI", FailingOpenAI)

    with pytest.raises(RuntimeError, match="programming defect"):
        llm_review.review_issues(
            Settings(llm_api_key="configured"),
            "中文，，文本",
            [_review_candidate()],
        )


def test_invalid_provider_response_degrades_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InvalidCompletions:
        def create(self, **kwargs: object) -> object:
            del kwargs
            message = type("Message", (), {"content": "not-json"})()
            choice = type("Choice", (), {"message": message})()
            return type("Response", (), {"choices": [choice]})()

    class InvalidOpenAI:
        def __init__(self, **kwargs: object) -> None:
            del kwargs
            self.chat = type("Chat", (), {"completions": InvalidCompletions()})()

    monkeypatch.setattr(llm_review, "OpenAI", InvalidOpenAI)

    issues, stats = llm_review.review_issues(
        Settings(llm_api_key="configured"),
        "中文，，文本",
        [_review_candidate()],
    )

    assert len(issues) == 1
    assert stats["failed"] is True
    assert stats["failure_code"] == "llm_invalid_response"
    assert stats["retryable"] is False


def test_invalid_provider_response_schema_degrades_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InvalidCompletions:
        def create(self, **kwargs: object) -> object:
            del kwargs
            message = type(
                "Message",
                (),
                {"content": '[{"id": "not-an-index", "verdict": "real"}]'},
            )()
            choice = type("Choice", (), {"message": message})()
            return type("Response", (), {"choices": [choice]})()

    class InvalidOpenAI:
        def __init__(self, **kwargs: object) -> None:
            del kwargs
            self.chat = type("Chat", (), {"completions": InvalidCompletions()})()

    monkeypatch.setattr(llm_review, "OpenAI", InvalidOpenAI)

    issues, stats = llm_review.review_issues(
        Settings(llm_api_key="configured"),
        "中文，，文本",
        [_review_candidate()],
    )

    assert len(issues) == 1
    assert stats["failed"] is True
    assert stats["failure_code"] == "llm_invalid_response"
    assert stats["retryable"] is False
