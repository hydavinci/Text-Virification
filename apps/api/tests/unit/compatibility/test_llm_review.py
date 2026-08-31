import logging

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
    assert caplog.records[-1].getMessage() == "llm_review_provider_failed"
    assert caplog.records[-1].exc_info is not None


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
