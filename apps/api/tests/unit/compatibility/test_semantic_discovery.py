import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from text_verification.compatibility import llm_review
from text_verification.compatibility.adapters import text_to_document_model
from text_verification.config import Settings
from text_verification.domain.documents import FileType
from text_verification.domain.ports import CheckContext
from text_verification.domain.verification import (
    VerificationOptions,
    decode_verification_options,
    encode_verification_options,
)


def test_discovery_option_is_opt_in_and_survives_persistence_and_context() -> None:
    assert decode_verification_options({}).enable_semantic_discovery is False
    options = VerificationOptions(enable_semantic_discovery=True)
    restored = decode_verification_options(encode_verification_options(options))
    assert CheckContext.from_options(restored).enable_semantic_discovery is True


def _discover(monkeypatch, text, response, *, context=None, **settings):
    from text_verification.compatibility.semantic_discovery import discover_issues

    calls = []

    class Client:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=self)

        def create(self, **kwargs):
            calls.append(kwargs)
            payload = response(kwargs) if callable(response) else response
            if isinstance(payload, dict):
                excerpts = json.loads(kwargs["messages"][1]["content"])["untrusted_excerpts"]
                payload = {"reviewed_chunk_ids": [item["chunk_id"] for item in excerpts], **payload}
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(payload)),
                finish_reason="stop",
            )])

    monkeypatch.setattr(llm_review, "OpenAI", Client)
    document = text_to_document_model(text=text, source_name="input.txt", file_type=FileType.TXT)
    resolved = Settings(
        _env_file=None,
        llm_api_key="test-only",
        llm_semantic_discovery_allowed=True,
        **settings,
    )
    findings, metadata = discover_issues(
        resolved, document,
        context or CheckContext(enable_semantic_discovery=True, verification_run_id=uuid4()),
        (),
    )
    return findings, metadata, calls


def _finding(**updates):
    return {
        "chunk_id": 0,
        "original": "He go",
        "suggestions": ["He goes"],
        "type": "grammar",
        "confidence": 0.86,
        "reason": "Subject and verb disagree.",
        **updates,
    }


def test_source_anchored_semantic_findings_are_manual_and_heuristic(monkeypatch) -> None:
    findings, metadata, calls = _discover(
        monkeypatch, "He go to school.", {"findings": [_finding()]},
    )
    assert len(findings) == 1
    issue = findings[0]
    assert issue.original == "He go"
    assert issue.start == 0 and issue.end == 5
    assert issue.suggestion == "He goes"
    assert issue.auto_fixable is False
    assert issue.confidence == 0.86
    assert issue.source == "llm_semantic"
    assert metadata["confidence_kind"] == "heuristic_not_probability"
    assert metadata["performed"] is True
    assert calls[0]["response_format"] == {"type": "json_object"}


def test_discovery_uses_the_selected_package_policy_in_system_instructions(monkeypatch) -> None:
    _, _, calls = _discover(monkeypatch, "正常文本。", {"findings": []})
    system = calls[0]["messages"][0]["content"]
    assert "通用文档" in system
    assert "保留日常口吻" in system
    assert "NOT a compliance" in system


@pytest.mark.parametrize("updates", [
    {"original": "not present"},
    {"type": "banned_word"},
    {"confidence": float("nan")},
    {"confidence": float("inf")},
    {"confidence": True},
    {"confidence": 1.1},
    {"confidence": 10**400},
    {"confidence": -(10**400)},
    {"confidence": 0.1},
    {"suggestions": ["", "He go"]},
    {"suggestions": ["He goes", "He goes"]},
    {"start": 1},
    {"chunk_id": True},
])
def test_invalid_findings_are_explicitly_rejected(monkeypatch, updates) -> None:
    findings, metadata, _ = _discover(
        monkeypatch, "He go to school.", {"findings": [_finding(**updates)]},
    )
    assert findings == ()
    assert metadata["rejected"] == 1
    assert metadata["degraded"] is True


def test_repeated_spans_require_explicit_correct_offsets(monkeypatch) -> None:
    text = "He go home. He go to school."
    findings, metadata, _ = _discover(monkeypatch, text, {"findings": [_finding()]})
    assert findings == ()
    findings, _, _ = _discover(
        monkeypatch, text, {"findings": [_finding(start=12)]},
    )
    assert len(findings) == 1
    assert findings[0].start == 12


def test_deduplicates_same_intent_but_retains_conflicting_suggestions(monkeypatch) -> None:
    findings, metadata, _ = _discover(monkeypatch, "He go home.", {"findings": [
        _finding(), _finding(), _finding(suggestions=["He went"]),
    ]})
    assert [issue.suggestion for issue in findings] == ["He goes", "He went"]
    assert metadata["duplicates"] == 1


@pytest.mark.parametrize("text,context", [
    ("`He go` is sample code.", {}),
    ("```\nHe go\n```", {}),
    ("He go home.", {
        "custom_glossary": ({"original": "He go", "standard": "Product"},),
    }),
    ("He go home.", {"banned_words": ("He goes",)}),
])
def test_respects_technical_regions_and_user_constraints(monkeypatch, text, context) -> None:
    findings, metadata, _ = _discover(
        monkeypatch, text, {"findings": [_finding()]},
        context=CheckContext(enable_semantic_discovery=True, **context),
    )
    assert findings == ()


def test_fair_bounded_chunks_cover_document_tail_and_keep_instructions_separate(monkeypatch):
    text = "\n\n".join(f"Paragraph {i}: He go home. " + "context " * 30 for i in range(30))
    findings, metadata, calls = _discover(
        monkeypatch, text, {"findings": []},
        llm_semantic_max_chunks=3, llm_semantic_chunk_chars=300,
        llm_semantic_context_chars=40,
    )
    assert findings == ()
    assert metadata["truncated"] is True
    assert metadata["sampled_chunks"] == 3
    assert metadata["sampled_ranges"][-1][1] == len(text)
    assert metadata["source_chars_sent"] <= 3 * (300 + 80)
    assert text not in calls[0]["messages"][1]["content"]
    assert "untrusted" in calls[0]["messages"][0]["content"].lower()


def test_default_off_does_not_construct_client(monkeypatch):
    findings, metadata, calls = _discover(
        monkeypatch, "He go.", {"findings": []}, context=CheckContext(),
    )
    assert findings == () and calls == []
    assert metadata["enabled"] is False


def test_server_permission_required_even_with_request_and_key(monkeypatch):
    from text_verification.compatibility.semantic_discovery import discover_issues

    def forbidden_client(**kwargs):
        pytest.fail("Provider must not be contacted without server permission")

    monkeypatch.setattr(llm_review, "OpenAI", forbidden_client)
    findings, metadata = discover_issues(
        Settings(_env_file=None, llm_api_key="test-only"),
        text_to_document_model(text="He go.", source_name="input.txt", file_type=FileType.TXT),
        CheckContext(enable_semantic_discovery=True), (),
    )
    assert findings == ()
    assert metadata["failure_code"] == "semantic_provider_not_allowed"
    assert metadata["degraded"] is True


@pytest.mark.parametrize("payload", [
    {"findings": [], "reviewed_chunk_ids": []},
    {"findings": [], "reviewed_chunk_ids": [0, 0]},
    {"findings": [], "reviewed_chunk_ids": [True]},
    {"findings": [], "unexpected": True},
    [],
])
def test_incomplete_or_invalid_envelopes_fail_closed(monkeypatch, payload):
    findings, metadata, _ = _discover(monkeypatch, "He go home.", payload)
    assert findings == ()
    assert metadata["failed"] is True
    assert metadata["failure_code"] == "llm_invalid_response"


def test_confidence_is_capped_and_not_derived_from_severity(monkeypatch):
    findings, _, _ = _discover(monkeypatch, "He go home.", {"findings": [
        _finding(confidence=1.0),
        _finding(confidence=0.7, suggestions=["He went"]),
    ]})
    assert [issue.confidence for issue in findings] == [0.9, 0.7]
    assert findings[0].severity == findings[1].severity


def test_provider_failure_retains_local_findings_and_reports_safe_degradation(monkeypatch):
    import httpx
    from openai import APITimeoutError

    def timeout(kwargs):
        raise APITimeoutError(request=httpx.Request("POST", "https://provider.invalid"))

    findings, metadata, _ = _discover(monkeypatch, "He go home.", timeout)
    assert findings == ()
    assert metadata["failed"] is True and metadata["retryable"] is True
    assert "provider.invalid" not in repr(metadata)


def test_technical_examples_are_masked_before_transmission(monkeypatch):
    text = "He go home.\n`test_token_123456789`\nhttps://example.invalid/private\n"
    _, _, calls = _discover(monkeypatch, text, {"findings": []})
    assert "test_token_123456789" not in calls[0]["messages"][1]["content"]
    assert "https://example.invalid/private" not in calls[0]["messages"][1]["content"]


def test_suggestions_cannot_introduce_banned_phrases_across_span_boundaries(monkeypatch):
    findings, metadata, _ = _discover(
        monkeypatch, "He go home.", {"findings": [_finding()]},
        context=CheckContext(enable_semantic_discovery=True, banned_words=("He goes home",)),
    )
    assert findings == ()
    assert metadata["rejected"] == 1


def test_suggestions_cannot_introduce_nonstandard_glossary_across_boundaries(monkeypatch):
    findings, metadata, _ = _discover(
        monkeypatch, "He go home.", {"findings": [_finding()]},
        context=CheckContext(enable_semantic_discovery=True, custom_glossary=(
            {"original": "He goes home", "standard": "He returns home"},
        )),
    )
    assert findings == ()
    assert metadata["rejected"] == 1


@pytest.mark.parametrize("updates", [
    {"suggestions": ["He goes\ud800"]},
    {"reason": "reason\ud800"},
])
def test_invalid_unicode_never_enters_persisted_findings(monkeypatch, updates):
    findings, metadata, _ = _discover(
        monkeypatch, "He go home.", {"findings": [_finding(**updates)]},
    )
    assert findings == ()
    assert metadata["rejected"] == 1


@pytest.mark.parametrize("text", [
    "The formula $He go$ is an example.",
    r"The formula \(He go\) is an example.",
    "The formula $$He go$$ is an example.",
])
def test_formula_regions_are_not_rewritten(monkeypatch, text):
    findings, _, calls = _discover(monkeypatch, text, {"findings": [_finding()]})
    assert findings == ()
    assert "He go" not in calls[0]["messages"][1]["content"]


def test_unicode_offsets_use_source_code_points(monkeypatch):
    findings, _, _ = _discover(
        monkeypatch, "😀 He go home.", {"findings": [_finding(start=2)]},
    )
    assert findings[0].start == 2 and findings[0].end == 7


def test_semantic_results_respect_global_issue_budget(monkeypatch):
    from text_verification.compatibility import semantic_discovery

    monkeypatch.setattr(semantic_discovery, "MAX_VERIFICATION_ISSUES", 0, raising=False)
    findings, metadata, calls = _discover(
        monkeypatch, "He go home.", {"findings": [_finding()]},
    )
    assert findings == ()
    assert calls == []
    assert metadata["failure_code"] == "semantic_issue_limit"


def test_shared_technical_standard_rows_are_masked(monkeypatch):
    text = "He go home.\nGB 123 | He go technical specimen.\nNatural prose."
    _, _, calls = _discover(monkeypatch, text, {"findings": []})
    assert "technical specimen" not in calls[0]["messages"][1]["content"]


def test_ascii_glossary_and_banned_terms_use_shared_token_boundaries(monkeypatch):
    findings, metadata, _ = _discover(
        monkeypatch, "He go home.", {"findings": [_finding()]},
        context=CheckContext(
            enable_semantic_discovery=True,
            custom_glossary=({"original": "H", "standard": "Letter H"},),
            banned_words=("go",),
        ),
    )
    # The source contains the whole banned token "go", so it cannot be replaced.
    assert findings == ()
    findings, metadata, _ = _discover(
        monkeypatch, "He go home.", {"findings": [_finding()]},
        context=CheckContext(
            enable_semantic_discovery=True,
            custom_glossary=({"original": "H", "standard": "Letter H"},),
            banned_words=("goesWrong",),
        ),
    )
    assert len(findings) == 1


def test_oversized_provider_confidence_degrades_without_losing_local_findings(monkeypatch):
    from text_verification.application.factory import build_default_verification_pipeline
    from text_verification.application.verification_pipeline import VerificationCommand
    from text_verification.domain.verification import VerificationExecutionMode

    _, metadata, _ = _discover(
        monkeypatch, "He go home.", {"findings": [_finding(confidence=10**400)]},
    )
    assert metadata["rejected"] == 1 and metadata["degraded"] is True
    pipeline = build_default_verification_pipeline(Settings(
        _env_file=None, llm_api_key="test-only", llm_semantic_discovery_allowed=True,
    ))
    result = pipeline.run(VerificationCommand(
        document_id=uuid4(), source_path=None, direct_text="He go home.",
        source_name="input.txt", file_type=FileType.TXT,
        options=VerificationOptions(
            enable_semantic_discovery=True, enable_security=False, enable_sensitive=False,
            custom_glossary=({"original": "He go", "standard": "He goes"},),
        ),
        execution_mode=VerificationExecutionMode.SYNCHRONOUS,
    ))
    assert any(issue.type == "custom_term" and issue.original == "He go" for issue in result.issues)
    assert not any(issue.source == "llm_semantic" for issue in result.issues)
    assert result.degradation.is_degraded
    assert "semantic_discovery_failed" in result.degradation.reasons
    assert result.summary.llm_review["semantic_discovery"]["rejected"] == 1
