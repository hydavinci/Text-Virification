from uuid import uuid4

import pytest

from text_verification.compatibility.adapters import (
    legacy_issues_to_domain,
    text_to_document_model,
)
from text_verification.compatibility.analyzer import TextAnalyzer
from text_verification.domain.documents import FileType


def analyze(text: str, **options: object):
    return TextAnalyzer().analyze(
        text, enable_security=False, enable_sensitive=False, **options,
    )


@pytest.mark.parametrize("text", [
    "The dose is low.",
    "Avoid cliches.",
    "这是认真的工作态度。",
    "我们通过认真研究使方案更加完善。",
    "链接 https://example.test/中文?q=1",
    "示例 `recieve(中文?` 不检查。",
    "```python\nrecieve = '中文?'\n```\n正常正文。",
])
def test_valid_text_and_technical_regions_are_not_corrected(text: str) -> None:
    assert analyze(text) == []


def test_glossary_matches_whole_english_tokens_not_identifier_fragments() -> None:
    issues = analyze(
        "MAIL AI2 AI_name AI。",
        custom_glossary=[{"original": "AI", "standard": "人工智能"}],
    )
    glossary = [issue for issue in issues if issue.rule_id == "custom_glossary"]
    assert [(issue.position, issue.end_position) for issue in glossary] == [(17, 19)]


def test_conflicting_rules_are_retained_with_user_rule_first() -> None:
    issues = analyze(
        "帐号",
        custom_glossary=[{"original": "帐号", "standard": "账户标识"}],
        banned_words=["帐号"],
    )
    assert [(issue.rule_id, issue.suggestion) for issue in issues] == [
        ("custom_glossary", "账户标识"),
        ("banned_word", "（请替换或删除该禁用词）"),
        ("cn_typo", "账号"),
    ]


def test_different_suggestions_for_same_rule_have_distinct_domain_ids() -> None:
    text = "AI"
    issues = analyze(text, custom_glossary=[
        {"original": "AI", "standard": "人工智能"},
        {"original": "AI", "standard": "智能系统"},
    ])
    document = text_to_document_model(text=text, source_name="text", file_type=FileType.TXT)
    converted = legacy_issues_to_domain(issues, document, uuid4())
    assert len(converted) == 2
    assert len({issue.issue_id for issue in converted}) == 2


def test_same_formatting_edit_is_coalesced_without_losing_rule_evidence() -> None:
    issues = analyze("中文,正文。")
    assert len(issues) == 1
    assert issues[0].suggestion == "，"
    assert "half_in_cn_context" in issues[0].description


def test_repeated_number_errors_keep_each_source_location() -> None:
    issues = [i for i in analyze("数量5五，另有5五。") if i.rule_id == "mixed_num_format"]
    assert [(i.position, i.end_position) for i in issues] == [(2, 4), (7, 9)]
    assert all(i.suggestion is None for i in issues)


@pytest.mark.parametrize(("text", "expected"), [
    ("1. 第一项\n3. 第三项\n2. 第二项", ["numbering_gap", "numbering_order"]),
    ("1. 第一项\n2. 第二项\n2. 重复项\n3. 第三项", ["numbering_duplicate"]),
    ("1. 第一项\n3. 第三项\n5. 第五项", ["numbering_gap", "numbering_gap"]),
    ("1. 第一项\n2. 第二项\n\n另一列表\n1. 新第一项\n2. 新第二项", []),
    ("1. 外层\n  1. 内层\n  2. 内层\n2. 外层", []),
    ("版本\n1.2.3\n2.4.0\n4.0.0", []),
])
def test_numbering_checks_follow_local_order_and_nesting(text: str, expected: list[str]) -> None:
    issues = [i for i in analyze(text) if i.rule_id.startswith("numbering_")]
    assert [i.rule_id for i in issues] == expected
    assert all(i.original == text[i.position:i.end_position] for i in issues)
    assert all(i.suggestion is None for i in issues)


def test_unterminated_grammar_has_same_findings_as_terminated_text() -> None:
    assert any(i.rule_id == "redundant_de" for i in analyze("这是的的测试"))


def test_noun_phrase_protection_does_not_hide_clear_adverb_error() -> None:
    issues = analyze("他认真的完成任务。")
    assert any(i.rule_id == "de_vs_di" and "认真地" in i.suggestion for i in issues)


def test_definition_exempts_only_defined_pair_not_other_variants() -> None:
    text = "正文采用苹果公司（Apple）。其他地方写作Apple公司。"
    issues = [i for i in analyze(text) if i.rule_id == "term_equivalence"]
    assert [(i.original, i.suggestion) for i in issues] == [("Apple公司", "苹果公司")]


def test_explicit_abbreviation_definition_allows_later_abbreviation() -> None:
    assert not any(
        i.rule_id == "term_equivalence"
        for i in analyze("采用人工智能（AI）。后文使用AI和人工智能。")
    )


def test_all_noncanonical_term_occurrences_are_anchored() -> None:
    text = "微软发布产品。Microsoft更新。Microsoft维护。"
    issues = [i for i in analyze(text) if i.rule_id == "term_equivalence"]
    assert [(i.position, i.end_position) for i in issues] == [(7, 16), (19, 28)]


def test_heuristic_confidence_is_not_certainty_for_style_typo_entries() -> None:
    text = "免费赠送"
    document = text_to_document_model(text=text, source_name="text", file_type=FileType.TXT)
    issues = legacy_issues_to_domain(analyze(text), document, uuid4())
    assert len(issues) == 1
    assert issues[0].type == "expression"
    assert issues[0].severity.value != "error"
    assert issues[0].confidence < 0.8


def test_manual_number_advice_is_not_auto_fixable() -> None:
    text = "1. 首项\n3. 末项"
    document = text_to_document_model(text=text, source_name="text", file_type=FileType.TXT)
    issues = legacy_issues_to_domain(analyze(text), document, uuid4())
    assert len(issues) == 1
    assert issues[0].auto_fixable is False


def test_code_delimiters_do_not_close_prose_brackets_or_quotes() -> None:
    text = '正文（示例 `)` 仍未闭合。\n他说 "示例 `" `。'
    issues = analyze(text)
    assert any(i.rule_id == "unmatched_bracket" and i.position == 2 for i in issues)
    assert any(i.rule_id == "unmatched_quote" for i in issues)


def test_unclosed_code_bracket_does_not_mask_following_prose_spacing() -> None:
    text = "代码 `(` 后面有API接口。"
    issues = analyze(text, enable_extended_rules=True)
    assert any(i.rule_id == "missing_space_cn_en" for i in issues)


def test_security_and_user_constraints_still_scan_protected_regions() -> None:
    issues = TextAnalyzer().analyze(
        "`person@example.test`", enable_sensitive=False, enable_security=True,
        banned_words=["person"],
    )
    assert {i.rule_id for i in issues} == {"pii_email", "banned_word"}


def test_literal_parenthesized_replacement_is_auto_fixable() -> None:
    text = "(正文）"
    document = text_to_document_model(text=text, source_name="text", file_type=FileType.TXT)
    issues = legacy_issues_to_domain(analyze(text), document, uuid4())
    assert issues
    assert all(i.auto_fixable for i in issues)
