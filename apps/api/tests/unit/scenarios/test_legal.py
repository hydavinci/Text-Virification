import importlib
import importlib.util

import pytest

from text_verification.scenarios.models import RuleInput


def check(name, text, complete=True):
    module = "text_verification.scenarios.legal"
    assert importlib.util.find_spec(module) is not None, "legal package is not implemented"
    profile = importlib.import_module(module).PROFILE
    rule = next(rule for rule in profile.rules if rule.rule_id == f"scenario.legal.{name}")
    return list(rule.check(RuleInput(text, complete_structure=complete)))


CONTRACT = "采购合同\n甲方：星河公司\n第一条 交付\n"


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_undefined_party_has_unicode_offsets(newline):
    text = ("备注😀\n" + CONTRACT + "乙方应交付设备。\n").replace("\n", newline)
    findings = check("undefined_party", text)
    assert len(findings) == 1
    assert text[findings[0].start:findings[0].end] == "乙方"
    assert findings[0].start == text.index("乙方")


@pytest.mark.parametrize("text,complete", [
    (CONTRACT + "乙方应交付设备。", False),
    ("研究文章\n第一条 示例\n乙方应交付设备。", True),
    (CONTRACT + "乙方：月亮公司\n乙方应交付设备。", True),
    (CONTRACT + "月亮公司（以下简称“乙方”）\n乙方应交付设备。", True),
    (CONTRACT + "乙方（供应商）：月亮公司\n乙方应交付设备。", True),
    (CONTRACT + "月亮公司（乙方）\n乙方应交付设备。", True),
    (CONTRACT + "“乙方应交付设备。”\n`乙方应交付设备`", True),
    ("采购合同摘录\n甲方：星河公司\n第一条 交付\n乙方应交付设备。", True),
    (CONTRACT + "乙方应交付设备。\n服务合同\n乙方：月亮公司", True),
])
def test_party_check_requires_unambiguous_complete_contract(text, complete):
    assert check("undefined_party", text, complete) == []


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_missing_clause_normalizes_chinese_and_arabic_numbers(newline):
    text = ("备注😀\n" + CONTRACT + "依照本合同第1条执行；违约处理见本合同第3条。\n")
    text = text.replace("\n", newline)
    findings = check("missing_clause", text)
    assert len(findings) == 1
    assert text[findings[0].start:findings[0].end] == "本合同第3条"
    assert findings[0].start == text.index("本合同第3条")


@pytest.mark.parametrize("tail,complete", [
    ("依照本合同第一条执行。", True),
    ("依照本合同第3条执行。", False),
    ("《其他合同》引用本合同第3条。", True),
    ("“本合同第3条”\n```\n本合同第3条\n```", True),
    ("第一条 另一章\n参见本合同第3条。", True),
    ("依照本合同第3条或附件协议执行。", True),
    ("第一二条 乱码编号\n参见本合同第3条。", True),
    ("第 3 条 交付细则\n参见本合同第3条。", True),
])
def test_clause_check_skips_excerpts_quotes_and_ambiguous_scope(tail, complete):
    assert check("missing_clause", CONTRACT + tail, complete) == []


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_amount_pair_inconsistency_is_local_and_manual(newline):
    text = "金额核对😀\n💰价款为人民币1000元（大写：贰仟元整）。\n".replace("\n", newline)
    findings = check("amount_pair", text, False)
    assert len(findings) == 1
    assert text[findings[0].start:findings[0].end] == "贰仟"
    assert findings[0].start == text.index("贰仟")
    assert findings[0].type == "expression"
    assert not hasattr(findings[0], "replacement")


@pytest.mark.parametrize("text", [
    "价款为1000元（大写：壹仟元整）。",
    "首付款1000元，尾款大写：贰仟元整。",
    "“1000元（大写：贰仟元整）”",
    "```\n1000元（大写：贰仟元整）\n```",
    "1000.50元（大写：壹仟元整）",
    "10000元（大写：壹仟元整）",
    "1000元（大写：壹贰元整）",
])
def test_amount_pair_ignores_separate_or_unsupported_amounts(text):
    assert check("amount_pair", text) == []


@pytest.mark.parametrize("text,expected", [
    ("0元（大写：壹元整）", "壹"),
    ("101元（大写：壹佰零壹元整）", None),
    ("1010元（大写：壹仟零壹拾元整）", None),
    ("9999元（大写：玖仟玖佰玖拾捌元整）", "玖仟玖佰玖拾捌"),
])
def test_amount_pair_handles_zero_internal_zeros_and_upper_bound(text, expected):
    findings = check("amount_pair", text)
    assert [text[item.start:item.end] for item in findings] == (
        [] if expected is None else [expected]
    )


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
@pytest.mark.parametrize("heading", [
    "第二条：付款", "第二条:付款", "第二条 付款", "第二条\t付款", "第二条", "第 2 条",
])
def test_clause_references_accept_all_shared_heading_separators(heading, newline):
    text = (CONTRACT + heading + "\n依照本合同第2条付款。\n").replace("\n", newline)
    assert check("missing_clause", text) == []


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
@pytest.mark.parametrize("mention", [
    "甲方与乙方签订本合同。",
    "乙方的联系方式另行提供。",
    "交付清单见附件。",
    "“乙方：月亮公司”",
    "```\n乙方：月亮公司\n```",
    "乙方：\n",
])
def test_mentions_and_non_prose_definitions_do_not_define_a_party(mention, newline):
    text = (CONTRACT + mention + "\n乙方应交付设备。").replace("\n", newline)
    findings = check("undefined_party", text)
    assert len(findings) == 1
    assert text[findings[0].start:findings[0].end] == "乙方"
    assert findings[0].start == text.rindex("乙方")


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
@pytest.mark.parametrize("definition", [
    "乙方：月亮公司", "乙方（供应商）：月亮公司", "月亮公司（乙方）",
    "月亮公司（以下简称“乙方”）", '月亮公司(以下简称"乙方")',
])
def test_explicit_party_definitions_survive_ordinary_mentions(definition, newline):
    text = (CONTRACT + definition + "\n甲方与乙方签订本合同。\n乙方应交付设备。")
    assert check("undefined_party", text.replace("\n", newline)) == []


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_unrelated_attachment_mention_does_not_disable_primary_clause_check(newline):
    text = (CONTRACT + "交付清单见附件。\n依照本合同第3条付款。").replace("\n", newline)
    findings = check("missing_clause", text)
    assert len(findings) == 1
    assert text[findings[0].start:findings[0].end] == "本合同第3条"


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
@pytest.mark.parametrize("heading", ["附件一：服务合同", "附件：采购合同", "附件一\n服务合同"])
def test_attached_contract_sections_remain_ambiguous(heading, newline):
    text = (CONTRACT + "乙方应交付设备，参见本合同第3条。\n" + heading + "\n乙方：月亮公司")
    text = text.replace("\n", newline)
    assert check("undefined_party", text) == []
    assert check("missing_clause", text) == []
