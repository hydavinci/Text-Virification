import importlib
import importlib.util

import pytest

from text_verification.scenarios.models import RuleInput


def rule(name):
    module = "text_verification.scenarios.technical"
    assert importlib.util.find_spec(module) is not None, "technical package is not implemented"
    profile = importlib.import_module(module).PROFILE
    return next(rule for rule in profile.rules if rule.rule_id == f"scenario.technical.{name}")


def check(name, text, complete=False):
    return list(rule(name).check(RuleInput(text, complete_structure=complete)))


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_parameter_collision_anchors_protected_json_key_only(newline):
    text = '参数定义：\nuser_id：用户编号😀\n示例：\n```json\n{"UserId": 1, "extra": 2}\n```\n'
    text = text.replace("\n", newline)
    findings = check("parameter_spelling", text)
    assert len(findings) == 1
    assert text[findings[0].start:findings[0].end] == "UserId"
    assert findings[0].start == text.index("UserId")
    assert rule("parameter_spelling").allow_technical


@pytest.mark.parametrize("text", [
    '参数定义：\nuser_id：用户编号\n示例：\n```json\n{"user_id": 1, "extra": 2}\n```',
    '参数定义：\nuser_id：用户编号\n示例：\n```json\n{"unknown": 1}\n```',
    '参数定义：\nuser_id：编号\nUserId：另一个参数\n示例：\n```json\n{"USERID": 1}\n```',
    '参数定义：\nuser_id：编号\n示例：\n```json\n{"nested": {"UserId": 1}}\n```',
    '参数定义：\nuser_id：编号\n示例：\n```json\n{"UserId": 1}\n```\n参数定义：\nother：其他',
    '“参数定义：user_id；示例：UserId”',
    '参数定义：\nuser_id：编号\n示例：\n```json\n{"UserId": 1, "UserId": 2}\n```',
])
def test_parameter_check_skips_unknown_keys_and_ambiguous_context(text):
    assert check("parameter_spelling", text) == []


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
@pytest.mark.parametrize("opening,closing", [("[", "]"), ('{"extra":', "}")])
def test_parameter_check_rejects_deep_nesting_before_json_decoding(opening, closing, newline):
    body = '{"extra":' + opening * 12000 + "0" + closing * 12000 + "}"
    text = "参数定义：\nuser_id：用户编号\n示例：\n```json\n" + body + "\n```"
    assert check("parameter_spelling", text.replace("\n", newline)) == []


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
@pytest.mark.parametrize("body", [
    r'{"prefix\"UserId": 1}',
    r'{"prefix\\\"UserId": 1}',
    r'{"extra": "prefix\"UserId", "unknown": 1}',
    r'{"extra": "{}[] \"UserId\": 1", "user_id": 1}',
    r'{"prefix{}[]\"UserId": "[]{} \"UserId\": 1"}',
    r'{"User\u0049d": 1}',
])
def test_parameter_check_never_matches_inside_escaped_keys_or_values(body, newline):
    text = "参数定义：\nuser_id：用户编号\n示例：\n```json\n" + body + "\n```"
    assert check("parameter_spelling", text.replace("\n", newline)) == []


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
@pytest.mark.parametrize("body", [
    r'{"extra": "{}[]", "UserId": 1}',
    r'{"extra": "{}[] \"UserId\": 1", "UserId": 1}',
    r'{"prefix{}[]\"UserId": "{}[] \"UserId\": 1", "UserId": 1}',
    r'{"extra": "ends with backslash\\", "UserId": 1}',
])
def test_parameter_check_preserves_real_key_offsets_after_string_literals(body, newline):
    text = "参数定义：\nuser_id：用户编号😀\n示例：\n```json\n" + body + "\n```"
    text = text.replace("\n", newline)
    findings = check("parameter_spelling", text)
    assert len(findings) == 1
    assert text[findings[0].start:findings[0].end] == "UserId"
    assert findings[0].start == text.rindex('"UserId":') + 1


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_current_version_outside_explicit_supported_range(newline):
    text = "说明😀\n支持版本：1.2.0 - 2.0.0\n当前版本：2.1.0\n".replace("\n", newline)
    findings = check("version_range", text)
    assert len(findings) == 1
    assert text[findings[0].start:findings[0].end] == "2.1.0"
    assert findings[0].start == text.index("2.1.0")


@pytest.mark.parametrize("text", [
    "支持版本：1.2.0 - 2.0.0\n当前版本：2.0.0",
    "支持版本：1.2 - 2.0\n当前版本：1.10",
    "支持版本：1.2 - 2.0\n当前版本：2.1-beta",
    "支持版本：1.2 - 2.0\n当前版本：2.1（另一产品）",
    "支持版本：2.0 - 1.2\n当前版本：2.1",
    "支持版本：1.2 - 2.0\n# 另一产品\n当前版本：2.1",
    "支持版本：1.2 - 2.0\n当前版本：2.1\n支持版本：2.0 - 3.0",
    "```\n支持版本：1.2 - 2.0\n当前版本：2.1\n```",
    "当前版本：2.1",
])
def test_version_range_is_numeric_local_and_unambiguous(text):
    assert check("version_range", text) == []


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_missing_step_with_complete_clear_sequence(newline):
    text = "操作步骤：\n步骤1：打开应用😀。\n步骤2：失败时返回步骤3。\n".replace("\n", newline)
    findings = check("missing_step", text, True)
    assert len(findings) == 1
    assert text[findings[0].start:findings[0].end] == "步骤3"
    assert findings[0].start == text.index("步骤3")
    assert rule("missing_step").requires_complete_structure


@pytest.mark.parametrize("text,complete", [
    ("操作步骤：\n步骤1：打开。\n步骤2：返回步骤1。", True),
    ("操作步骤：\n步骤1：打开。\n步骤2：返回步骤3。", False),
    ("操作步骤摘录：\n步骤1：打开。\n步骤2：返回步骤3。", True),
    ("操作步骤：\n步骤1：打开。\n步骤3：返回步骤4。", True),
    ("操作步骤：\n步骤1：打开。\n步骤2：返回步骤3。\n操作步骤：\n步骤1：关闭。", True),
    ("操作步骤：\n步骤1：打开。\n步骤2：“返回步骤3”。", True),
    ("操作步骤：\n步骤1：打开。\n步骤2：`返回步骤3`。", True),
    ("操作步骤：\n步骤1：打开。\n步骤2：返回步骤3。\n# 其他流程\n步骤3：关闭。", True),
    ("操作步骤：\n步骤1：打开。\n步骤2：关闭。\n其他操作\n失败时返回步骤3。", True),
])
def test_step_references_skip_excerpts_literals_and_multiple_workflows(text, complete):
    assert check("missing_step", text, complete) == []


def test_parameter_underscores_are_checked_without_comparing_example_values():
    text = '参数定义：\nretryCount：默认3\n示例：\n```json\n{"retry_count": 5}\n```'
    findings = check("parameter_spelling", text)
    assert len(findings) == 1
    assert text[findings[0].start:findings[0].end] == "retry_count"
