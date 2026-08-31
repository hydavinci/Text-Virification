from text_verification.compatibility import service
from text_verification.compatibility.models import Scenario
from text_verification.config import Settings
from text_verification.domain.verification import (
    VerificationAnalysisMode,
    VerificationExecutionMode,
)


def _analyze(settings: Settings):
    return service.analyze(
        settings,
        text="中文，，文本",
        filename="直接输入文本",
        file_id=None,
        file_extension=None,
        scenario=Scenario.GENERAL,
        custom_glossary=[],
        banned_words=[],
        enable_security=False,
        enable_sensitive=False,
        enable_ad_extreme=False,
    )


def test_disabled_llm_is_local_only_without_degradation() -> None:
    result = _analyze(Settings(llm_api_key=""))

    assert result.execution_mode is VerificationExecutionMode.SYNCHRONOUS
    assert result.analysis_mode is VerificationAnalysisMode.LOCAL_ONLY
    assert result.degradation.is_degraded is False
    assert result.degradation.reasons == ()


def test_successful_llm_review_reports_local_plus_llm(
    monkeypatch,
) -> None:
    def successful_review(settings, text, issues):
        del settings, text
        return issues, {
            "enabled": True,
            "performed": True,
            "failed": False,
            "failure_code": None,
            "reason": "",
        }

    monkeypatch.setattr(service, "review_issues", successful_review)

    result = _analyze(Settings(llm_api_key="configured"))

    assert result.execution_mode is VerificationExecutionMode.SYNCHRONOUS
    assert result.analysis_mode is VerificationAnalysisMode.LOCAL_PLUS_LLM
    assert result.degradation.is_degraded is False


def test_failed_configured_llm_falls_back_and_marks_degradation(
    monkeypatch,
) -> None:
    def failed_review(settings, text, issues):
        del settings, text
        return issues, {
            "enabled": True,
            "performed": False,
            "failed": True,
            "failure_code": "llm_provider_error",
            "reason": "大模型调用失败，已回退纯规则结果",
        }

    monkeypatch.setattr(service, "review_issues", failed_review)

    result = _analyze(Settings(llm_api_key="configured"))

    assert result.analysis_mode is VerificationAnalysisMode.LOCAL_ONLY
    assert result.degradation.is_degraded is True
    assert result.degradation.reasons == ("llm_review_failed",)
