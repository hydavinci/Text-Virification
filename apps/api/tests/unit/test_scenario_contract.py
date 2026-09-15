import re
import subprocess
import sys

import pytest

from text_verification.compatibility.analyzer import TextAnalyzer
from text_verification.scenarios.models import RuleInput


def test_scenario_prose_matching_preserves_offsets_and_excludes_examples() -> None:
    text = '😀尽快完成。示例 `尽快完成`，原话“尽快完成”。'
    document = RuleInput(text=text, complete_structure=True)
    assert [m.span() for m in document.prose_matches(re.compile("尽快完成"))] == [(1, 5)]


def test_scenario_lines_preserve_unicode_source_offsets() -> None:
    document = RuleInput(text="😀标题\n\n  正文\n", complete_structure=True)
    assert list(document.lines()) == [(0, 3, "😀标题"), (5, 9, "  正文")]


def test_prose_checks_preserve_multiline_quotations() -> None:
    text = "原话：“请处理：\n尽快完成。”\n正文尽快完成。"
    document = RuleInput(text=text)
    matches = list(document.prose_matches(re.compile("尽快完成")))
    assert [match.start() for match in matches] == [text.rindex("尽快完成")]


def test_prose_checks_preserve_blockquotes_and_their_continuation_lines() -> None:
    text = "原文：\n> 尽快完成。\n延续引文：尽快完成。\n\n正文尽快完成。"
    document = RuleInput(text=text)
    matches = list(document.prose_matches(re.compile("尽快完成")))
    assert [match.start() for match in matches] == [text.rindex("尽快完成")]


def test_overlapping_quotation_forms_do_not_unprotect_the_outer_quote() -> None:
    text = "“第一段\n> 内层引文\n\n尽快完成。”\n正文尽快完成。"
    document = RuleInput(text=text)
    matches = list(document.prose_matches(re.compile("尽快完成")))
    assert [match.start() for match in matches] == [text.rindex("尽快完成")]


def test_general_profile_does_not_impose_formal_speech() -> None:
    issues = TextAnalyzer().analyze("咱们处理。", enable_sensitive=False, enable_security=False)
    assert not any(issue.type == "colloquial" for issue in issues)


def test_unknown_scenario_is_not_silently_treated_as_general() -> None:
    with pytest.raises(ValueError, match="scenario"):
        TextAnalyzer().analyze("正常文本。", scenario="unknown")


def test_quote_protection_remains_bounded_for_long_documents() -> None:
    script = """
import re
from text_verification.scenarios.models import RuleInput
document = RuleInput(text='“引用”正文' * 40000)
assert sum(1 for _ in document.prose_matches(re.compile('正文'))) == 40000
assert list(RuleInput(text='“' * 100000).prose_matches(re.compile('正文'))) == []
"""
    subprocess.run([sys.executable, "-c", script], check=True, timeout=4, capture_output=True)
