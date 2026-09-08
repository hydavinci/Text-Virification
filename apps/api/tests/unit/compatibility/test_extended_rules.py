from __future__ import annotations

import pytest

from text_verification.compatibility.analyzer import TextAnalyzer


def test_extended_rules_are_opt_in_and_preserve_default_findings() -> None:
    text = "文档API接口。\n\n\n" + "这是用于说明识别规则的长句" * 9 + "。"
    analyzer = TextAnalyzer()
    baseline = analyzer.analyze(text, enable_security=False, enable_sensitive=False)
    enabled = analyzer.analyze(
        text, enable_security=False, enable_sensitive=False, enable_extended_rules=True,
    )
    extended_ids = {"missing_space_cn_en", "multi_blank_line", "long_sentence_cn"}
    assert not (extended_ids & {issue.rule_id for issue in baseline})
    assert extended_ids <= {issue.rule_id for issue in enabled}
    assert {issue.rule_id for issue in baseline} <= {issue.rule_id for issue in enabled}


@pytest.mark.parametrize(
    ("text", "rule_id"),
    [
        ("这是用于说明识别规则的长句" * 9 + "。", "long_sentence_cn"),
        ("This sentence includes " + "another useful word " * 15 + ".", "long_sentence_en"),
    ],
)
def test_long_sentence_findings_are_source_anchored_manual_advice(
    text: str, rule_id: str,
) -> None:
    issues = TextAnalyzer().analyze(
        text, scenario="general", enable_security=False, enable_sensitive=False,
        enable_extended_rules=True,
    )
    issue = next(issue for issue in issues if issue.rule_id == rule_id)
    assert issue.original == text[issue.position:issue.end_position]
    assert issue.suggestion is None
    assert issue.layer == "discourse"


def test_long_sentence_advice_bounds_original_and_context_for_session_recovery() -> None:
    text = "这是一段需要人工拆分而非自动替换的长句" * 600 + "。"
    issues = TextAnalyzer()._check_long_sentences(text)
    assert len(issues) == 1
    issue = issues[0]
    assert issue.original == text[:200]
    assert issue.end_position == 200
    assert len(issue.context) < 300
    assert issue.suggestion is None


def test_unterminated_text_is_not_reported_as_a_complete_long_sentence() -> None:
    assert TextAnalyzer()._check_long_sentences("未结束的正文内容" * 1000) == []
    assert TextAnalyzer()._check_long_sentences("unfinished sentence " * 1000) == []


def test_extended_spacing_keeps_existing_protected_delimiters() -> None:
    text = "正文API接口，链接 https://example.com/a?q=中文2 和《代码API》。"
    issues = TextAnalyzer().analyze(
        text, enable_security=False, enable_sensitive=False, enable_extended_rules=True,
    )
    spacing = [issue for issue in issues if issue.rule_id == "missing_space_cn_en"]
    assert spacing
    assert all(issue.position < text.index("《") for issue in spacing)
    assert all(
        not text.index("https://") <= issue.position < text.index(" 和 ")
        for issue in spacing
    )
