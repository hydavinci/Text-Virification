import importlib
import importlib.util

import pytest

from text_verification.scenarios.models import RuleInput


def check(rule, text, *, complete=True, glossary=()):
    module = "text_verification.scenarios.academic"
    assert importlib.util.find_spec(module) is not None, "academic package is not implemented"
    profile = importlib.import_module(module).PROFILE
    spec = next(item for item in profile.rules if item.rule_id == f"scenario.academic.{rule}")
    return list(spec.check(RuleInput(text, complete, frozenset(glossary))))


def assert_hit(findings, text, fragment, *, last=False):
    start = text.rindex(fragment) if last else text.index(fragment)
    assert [(item.start, item.end) for item in findings] == [(start, start + len(fragment))]
    assert text[findings[0].start:findings[0].end] == fragment
    assert findings[0].description


@pytest.mark.parametrize(
    "text",
    [
        "😀文献[2]给出方法。\n参考文献\n[1] 张三，研究。",
        "Please see [2].\n## References\n[1] Smith, Study.",
    ],
)
def test_missing_explicit_citation_preserves_codepoint_span(text):
    assert_hit(check("citation_reference", text), text, "[2]")


@pytest.mark.parametrize(
    "text",
    [
        "文献[1]给出方法。\n参考文献\n[1] 张三，研究。",
        "文献[2]给出方法。",
        "文献[2]给出方法。\n参考文献\n[1] 第一条\n[1] 第二条",
        "文献[2]给出方法。\n参考文献\n[1] 第一条\n未编号的另一条",
        "文献[2]给出方法。\n参考文献\n[1] 第一条\n参考文献\n[3] 另一文献",
        "数组[2]是索引。\n参考文献\n[1] 张三，研究。",
        "See [2](https://example.org).\nReferences\n[1] Smith, Study.",
        '“文献[2]给出方法。”\n`文献[2]`\n参考文献\n[1] 张三，研究。',
        "```\n文献[2]\n```\n> 文献[2]\n参考文献\n[1] 张三，研究。",
        "文献[2]\n```\n参考文献\n[1] 示例\n```",
        "文献[2]\n参考文献\n[1] 第一条\n[2-3] 合并编号",
    ],
)
def test_citation_skips_matches_ambiguous_sources_and_examples(text):
    assert check("citation_reference", text) == []


def test_citation_does_not_infer_missing_reference_from_excerpt():
    assert check("citation_reference", "文献[2]\n参考文献\n[1] 第一条", complete=False) == []


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("😀见本文图2。\n图1：实验流程", "本文图2"),
        ("本文表3给出了结果。\n表1：参数", "本文表3"),
        ("See Figure 2 in this paper.\nFigure 1: Flow", "Figure 2"),
        ("See Table 3 in this document.\nTable 1: Results", "Table 3"),
    ],
)
def test_missing_local_figure_or_table_reference(text, fragment):
    assert_hit(check("caption_reference", text), text, fragment)


@pytest.mark.parametrize(
    "text",
    [
        "本文图1。\n图1：流程",
        "本文图2。",
        "本文图2。\n表1：参数",
        "文献中的图2显示结果。\n图1：流程",
        "See Figure 2 in Smith's paper.\nFigure 1: Flow",
        "本文图2。\n图1：流程\n图1：另一流程",
        "本文图2。\n图1：流程\n图2.1：分节编号",
        "本文图2.1。\n图1：流程",
        "本文图2(a)。\n图1：流程",
        "“本文图2”\n`本文图2`\n> 本文图2\n图1：流程",
        "```\n本文图2\n```\n图1：流程",
        "本文图2。\n```\n图1：示例\n```",
    ],
)
def test_caption_rule_skips_nonlocal_ambiguous_and_protected_content(text):
    assert check("caption_reference", text) == []


def test_caption_rule_skips_incomplete_document():
    assert check("caption_reference", "本文图2。\n图1：流程", complete=False) == []


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("😀术语说明\n缩写 ABC：甲乙丙\n缩写 ABC：丁戊己", "丁戊己"),
        ("Abbreviation ABC: Alpha Beta\nAbbreviation ABC: Another Concept", "Another Concept"),
    ],
)
def test_explicit_conflicting_abbreviation_definitions_in_same_block(text, fragment):
    assert_hit(check("abbreviation_definition", text), text, fragment)


@pytest.mark.parametrize(
    "text",
    [
        "DNA与RNA用于研究，NASA公布了结果。ABC尚未定义。",
        "缩写 ABC：甲乙丙\n缩写 ABC：甲乙丙",
        "Abbreviation ABC: Alpha Beta\nAbbreviation ABC: alpha   beta",
        "缩写 ABC：甲乙丙\n\n缩写 ABC：丁戊己",
        "缩写 ABC：甲乙丙\n## 另一个研究\n缩写 ABC：丁戊己",
        "缩写 ABC：甲乙丙\nAbbreviation ABC: Alpha Beta",
        "缩写 ABC：甲乙丙\n缩写 ABC：丁戊己或庚辛壬",
        "缩写 ABC：甲乙丙\n“缩写 ABC：丁戊己”",
        "缩写 ABC：甲乙丙\n> 缩写 ABC：丁戊己",
        "缩写 ABC：甲乙丙\n```\n缩写 ABC：丁戊己\n```",
    ],
)
def test_abbreviation_rule_avoids_first_use_guesses_translations_and_new_scopes(text):
    assert check("abbreviation_definition", text) == []


def test_glossary_exempts_explicit_abbreviation_conflict():
    text = "缩写 ABC：甲乙丙\n缩写 ABC：丁戊己"
    assert check("abbreviation_definition", text, glossary=("ABC",)) == []


def test_abbreviation_conflict_is_locally_checkable_in_excerpt():
    text = "缩写 ABC：甲乙丙\n缩写 ABC：丁戊己"
    assert_hit(check("abbreviation_definition", text, complete=False), text, "丁戊己")


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize(
    ("rule", "text", "fragment"),
    [
        (
            "citation_reference",
            "😀摘要\n研究结果表明[2]。\n参考文献\n[1] 张三，研究。",
            "[2]",
        ),
        ("caption_reference", "😀正文\n本文图2。\n图1 流程", "本文图2"),
        (
            "abbreviation_definition",
            "😀术语\n缩写 AI：人工智能\n缩写 AI：人工智能 Artificial Intelligence\n"
            "缩写 AI：自动推理",
            "自动推理",
        ),
    ],
)
def test_v2_academic_hits_preserve_lf_and_crlf_offsets(newline, rule, text, fragment):
    text = text.replace("\n", newline)
    assert_hit(check(rule, text), text, fragment)


@pytest.mark.parametrize(
    "text",
    [
        "缩写 AI：人工智能\n缩写 AI：人工智能 Artificial Intelligence",
        "缩写 AI：人工智能 Artificial Intelligence\n缩写 AI：人工智能",
        "Abbreviation AI: Artificial Intelligence\n缩写 AI：人工智能 Artificial Intelligence",
        "缩写 AI：人工智能 Artificial Intelligence\nAbbreviation AI: Artificial Intelligence",
        "缩写 AI：人工智能\n缩写 AI：另一含义 Another Interpretation",
        "缩写 AI：人工智能 Artificial Intelligence\n缩写 AI：机器智能 Machine Intelligence",
        "缩写 AI：人工智能\n缩写 AI：Artificial Intelligence 人工智能",
    ],
)
def test_bilingual_expansion_does_not_assert_translation_conflict(text):
    assert check("abbreviation_definition", text) == []


def test_monolingual_conflict_survives_intervening_other_language_definition():
    text = "缩写 AI：人工智能\nAbbreviation AI: Artificial Intelligence\n缩写 AI：自动推理"
    assert_hit(check("abbreviation_definition", text), text, "自动推理")


@pytest.mark.parametrize(
    "body",
    [
        "数组[2]。",
        "研究结果表明数组[2]。",
        "研究结果表明[2][3]。",
        "研究结果表明[[2]]。",
        "研究结果表明[2](https://example.org)。",
        "研究结果表明[2] [link]。",
        "[研究结果表明][2]。",
        "[2]: https://example.org",
        "研究结果表明[2]为索引。",
        "研究结果表明[1,2]。",
        "研究结果表明[1-2]。",
        "文献[2][3]",
        "假设研究结果表明[2]。",
        "“研究结果表明[2]。”",
        "`研究结果表明[2]。`",
        "> 研究结果表明[2]。",
        "```\n研究结果表明[2]。\n```",
    ],
)
def test_ordinary_citation_requires_unambiguous_narrative_not_bracket_syntax(body):
    assert check("citation_reference", f"{body}\n参考文献\n[1] 张三，研究。") == []


def test_ordinary_citation_still_requires_complete_unique_reference_section():
    text = "研究结果表明[2]。\n参考文献\n[1] 张三，研究。"
    assert check("citation_reference", text, complete=False) == []
    assert check("citation_reference", text + "\n[1] 李四，研究。") == []


@pytest.mark.parametrize(
    "text",
    [
        "本文图1。\n图1 流程",
        "本文图2。\n图1 流程\n图1 另一流程",
        "本文图2。\n图1 流程\n图2.1 分节流程",
        "文献中的图2。\n图1 流程",
        "本文图2。\n> 图1 流程",
        "本文图2。\n```\n图1 流程\n```",
    ],
)
def test_space_separated_captions_keep_ambiguity_and_protection_guards(text):
    assert check("caption_reference", text) == []
