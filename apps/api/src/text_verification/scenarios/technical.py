from __future__ import annotations

import json
import re
from collections.abc import Iterator

from .models import Finding, RuleInput, RuleSpec, ScenarioProfile

_DEFINITIONS = re.compile(r"^[ \t]*参数定义[：:][ \t]*\r?$", re.M)
_EXAMPLE = re.compile(r"^[ \t]*示例[：:][ \t]*\r?$", re.M)
_PARAMETER = re.compile(r"[ \t]*`?([A-Za-z][A-Za-z0-9_]*)`?[：:][^\n]+")
_JSON = re.compile(r"\s*```json[ \t]*\r?\n(?P<body>[^`]+)\r?\n```[ \t]*(?:\r?\n|$)")
_FLAT_JSON = re.compile(r'\s*\{(?:[^"{}\[\]]|"(?:[^"\\]|\\.)*")*\}\s*', re.S)
_JSON_STRING = re.compile(r'"(?:[^"\\]|\\.)*"(?:\s*:)?', re.S)
_KEY = re.compile(r'"(?P<key>[A-Za-z][A-Za-z0-9_]*)"\s*:')
_RELEASE = r"([0-9]{1,6}(?:\.[0-9]{1,6}){0,2})"
_SUPPORTED = re.compile(
    r"^[ \t]*支持版本[：:][ \t]*" + _RELEASE + r"[ \t]+-[ \t]+" + _RELEASE + r"[ \t]*\r?$",
    re.M,
)
_CURRENT = re.compile(r"^[ \t]*当前版本[：:][ \t]*" + _RELEASE + r"[ \t]*\r?$", re.M)
_SEQUENCE = re.compile(r"^[ \t]*操作步骤[：:][ \t]*\r?$", re.M)
_STEP = re.compile(r"^[ \t]*步骤([1-9][0-9]{0,3})[：:]", re.M)
_STEP_REFERENCE = re.compile(r"(?:返回|转到|跳转到|参见)(步骤([1-9][0-9]{0,3}))")


def _parameter_spelling(data: RuleInput) -> Iterator[Finding]:
    definitions = list(data.prose_matches(_DEFINITIONS))
    examples = list(data.prose_matches(_EXAMPLE))
    if len(definitions) != 1 or len(examples) != 1:
        return
    definition, example = definitions[0], examples[0]
    if definition.end() >= example.start():
        return
    names = {}
    for line in data.text[definition.end():example.start()].strip().splitlines():
        match = _PARAMETER.fullmatch(line)
        if not match:
            return
        name = match.group(1)
        normalized = name.lower().replace("_", "")
        if normalized in names:
            return
        names[normalized] = name
    block = _JSON.match(data.text, example.end())
    if not names or not block:
        return
    body = block.group("body")
    if not _FLAT_JSON.fullmatch(body):
        return
    try:
        pairs = json.loads(body, object_pairs_hook=list)
    except ValueError:
        return
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        return
    for token in _JSON_STRING.finditer(body):
        match = _KEY.fullmatch(token.group())
        if not match:
            continue
        key = match.group("key")
        defined = names.get(key.lower().replace("_", ""))
        if defined and defined != key:
            yield Finding(
                block.start("body") + token.start() + match.start("key"),
                block.start("body") + token.start() + match.end("key"),
                f"示例键名{key}与显式参数定义{defined}仅大小写或下划线不同，请人工核对。",
            )


def _release(value: str) -> tuple[int, ...]:
    parts = tuple(int(part) for part in value.split("."))
    return parts + (0,) * (3 - len(parts))


def _version_range(data: RuleInput) -> Iterator[Finding]:
    if data.text.count("支持版本") != 1 or data.text.count("当前版本") != 1:
        return
    supported = list(data.prose_matches(_SUPPORTED))
    current = list(data.prose_matches(_CURRENT))
    if len(supported) != 1 or len(current) != 1:
        return
    bounds, version = supported[0], current[0]
    if bounds.end() >= version.start() or data.text[bounds.end():version.start()].strip():
        return
    lower, upper = (_release(value) for value in bounds.groups())
    if lower <= upper and not lower <= _release(version.group(1)) <= upper:
        yield Finding(
            *version.span(1),
            "标注的当前版本不在紧邻的显式支持版本闭区间内，请人工核对产品及版本范围。",
        )


def _missing_step(data: RuleInput) -> Iterator[Finding]:
    if not data.complete_structure or re.search(r"摘录|节选|示例流程", data.text):
        return
    sequences = list(data.prose_matches(_SEQUENCE))
    if len(sequences) != 1:
        return
    start = sequences[0].end()
    if any(
        line.strip() and not _STEP.match(line)
        for line in data.text[start:].splitlines()
    ):
        return
    steps = list(data.prose_matches(_STEP))
    numbers = [int(match.group(1)) for match in steps]
    if len(steps) < 2 or steps[0].start() < start or numbers != list(range(1, len(steps) + 1)):
        return
    for match in data.prose_matches(_STEP_REFERENCE):
        if match.start() > start and int(match.group(2)) > len(steps):
            yield Finding(
                *match.span(1),
                "该引用超出本文单一连续步骤序列，请人工核对步骤编号；不推断缺失操作。",
            )


PROFILE = ScenarioProfile(
    id="technical",
    name="技术文档",
    description="基于显式参数、版本及完整操作序列核对内部一致性；支持LF/CRLF原文定位。",
    version="2",
    base_checks=(
        "punctuation", "brackets_quotes", "extra_spaces", "number_format",
        "chinese_typos", "variant_chars", "half_full_width", "missing_chars",
        "term_consistency", "expression_issues", "grammar_patterns", "repeated_words",
        "english_spelling",
    ),
    extended_checks=("spacing", "extended_english"),
    rules=(
        RuleSpec(
            "scenario.technical.parameter_spelling", "参数与示例键名核对",
            "仅单一“参数定义：”逐行ASCII名称定义及随后“示例：”JSON平面对象，"
            "核对去下划线并忽略大小写后唯一匹配的不同键名；未知扩展键不报缺定义，"
            "解码前排除字符串外的嵌套结构，重复键及定义冲突跳过；"
            "仅检查完整、无转义的ASCII键名，字符串内容不作结构或键名。"
            "仅此规则允许在代码键名上定位。",
            _parameter_spelling, allow_technical=True,
        ),
        RuleSpec(
            "scenario.technical.version_range", "显式支持版本核对",
            "仅相邻的唯一“支持版本：下界 - 上界/当前版本：版本”比较闭区间，"
            "限一至三段数字版本，缺省段按0；跳过预发布、倒置区间、附注及多上下文。",
            _version_range,
        ),
        RuleSpec(
            "scenario.technical.missing_step", "完整操作步骤引用核对",
            "仅完整文本单一“操作步骤：”及至少两条从1连续编号的“步骤N：”，"
            "标题后每个非空行必须是步骤行，核对返回/转到/跳转到/参见步骤N；"
            "跳过摘录、多流程、引文和代码。",
            _missing_step, requires_complete_structure=True,
        ),
    ),
    semantic_guidance=(
        "只依据本次技术文档内明确的参数定义、同产品版本说明及同一操作序列核对。"
        "代码、标识符、路径、版本及引文通常保留原样；仅显式定义与示例键名的"
        "唯一大小写/下划线冲突可作人工提示，不把未知扩展键判为漏定义。"
        "示例值可能覆盖默认值，不能据此推断矛盾；不同产品、流程或版本不可混比。"
        "抽样片段不能证明缺少步骤或定义，不编造未提供数据；不查询外部文档，"
        "不作安全或合规结论，全部建议仅供人工核对且不自动修改代码。"
    ),
)
