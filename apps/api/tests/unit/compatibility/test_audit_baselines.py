import pytest

from text_verification.compatibility import text_context
from text_verification.compatibility.adapters import legacy_issues_to_domain, text_to_document_model
from text_verification.compatibility.analyzer import TextAnalyzer
from text_verification.domain.documents import FileType
from text_verification.domain.ports import CheckContext


@pytest.mark.parametrize("text", [
    "采取措施，防止系统不再提供服务。",
    "采用心跳机制，避免设备不再响应。",
    "采用备用电源，阻止设备不再工作。",
])
def test_positive_actions_are_not_inverted_by_double_negation_rules(text: str) -> None:
    issues = TextAnalyzer().analyze(text, enable_security=False, enable_sensitive=False)
    assert not any(issue.rule_id == "illogic_double_neg" for issue in issues)


@pytest.mark.parametrize("text", ["防止事故不再发生。", "切忌不要忽略安全问题。"])
def test_suspected_negation_problems_require_manual_semantic_review(text: str) -> None:
    document = text_to_document_model(text=text, source_name="input", file_type=FileType.TXT)
    legacy = TextAnalyzer().analyze(text, enable_security=False, enable_sensitive=False)
    issues = legacy_issues_to_domain(legacy, document, CheckContext().verification_run_id)
    negations = [issue for issue in issues if issue.rule_id == "illogic_double_neg"]
    assert len(negations) == 1
    assert negations[0].suggestion is None
    assert not negations[0].auto_fixable
    assert negations[0].severity.value != "error"


def test_explicit_abbreviation_definitions_are_not_rewritten_as_terms() -> None:
    text = "缩写 AI：人工智能\n缩写 AI：人工智能\nAI方法用于研究。"
    issues = TextAnalyzer().analyze(text, enable_security=False, enable_sensitive=False)
    assert not any(issue.rule_id == "term_equivalence" for issue in issues)


def test_custom_glossary_remains_authoritative_over_document_definitions() -> None:
    issues = TextAnalyzer().analyze(
        "缩写 AI：人工智能", enable_security=False, enable_sensitive=False,
        custom_glossary=[{"original": "AI", "standard": "人工智能系统"}],
    )
    assert any(issue.rule_id == "custom_glossary" for issue in issues)


@pytest.mark.parametrize("heading", ["第一条 总则", "第 二 条 付款", "第三条 交付"])
def test_clause_heading_separators_are_not_deleted(heading: str) -> None:
    issues = TextAnalyzer().analyze(
        f"采购合同\n{heading}\n双方应履行合同约定的责任。",
        enable_security=False, enable_sensitive=False,
    )
    assert not any(issue.rule_id == "cn_extra_space" for issue in issues)


def test_shared_clause_recognition_accepts_common_delimiters_and_crlf() -> None:
    pattern = getattr(text_context, "CLAUSE_HEADING_PATTERN", None)
    assert pattern is not None
    text = "第一条 总则\r\n第2条：付款\r\n第三条\r\n本合同第4条引用。\r\n"
    assert [match.group(1) for match in pattern.finditer(text)] == ["一", "2", "三"]


def test_shared_abbreviation_recognition_retains_meaning_and_source_spans() -> None:
    pattern = getattr(text_context, "ABBREVIATION_DEFINITION_PATTERN", None)
    assert pattern is not None
    text = "😀标题\r\n缩写 AI：人工智能\r\nAbbreviation AI: Artificial Intelligence"
    assert [(m["abbr"], m["meaning"]) for m in pattern.finditer(text)] == [
        ("AI", "人工智能"), ("AI", "Artificial Intelligence"),
    ]
