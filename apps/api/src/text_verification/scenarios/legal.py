from __future__ import annotations

import re
from collections.abc import Iterator

from text_verification.compatibility.text_context import CLAUSE_HEADING_PATTERN

from .models import Finding, RuleInput, RuleSpec, ScenarioProfile

_TITLE = re.compile(r"^[ \t]*(?:#{1,3} )?[\u4e00-\u9fff]{0,20}合同[ \t]*\r?$", re.M)
_CLAUSE = CLAUSE_HEADING_PATTERN
_ATTACHED_CONTRACT = re.compile(
    r"^[ \t]*(?:#{1,6}[ \t]+)?附件[^\r\n]{0,40}合同[ \t]*\r?$", re.M
)
_REFERENCE = re.compile(r"本合同第([0-9]{1,3}|[零一二三四五六七八九十百]{1,6})条")
_PARTY = re.compile(r"[甲乙丙丁]方(?=应|须|必须|负责|同意|承诺)")
_DEFINITION = re.compile(
    r"^[ \t]*([甲乙丙丁]方)(?:[（(][^（）()\r\n]{1,30}[）)])?[ \t]*[：:][ \t]*"
    r"([^\s。；;，,“”\"`]{1,80})"
    r"|([\u4e00-\u9fffA-Za-z0-9·]{2,80})[ \t]*[（(]"
    r"(?:以下简称[“\"「]?)?([甲乙丙丁]方)[”\"」]?[）)]",
    re.M,
)
_AMOUNT = re.compile(
    r"(?<![\d.,])(?:人民币)?(?P<number>0|[1-9][0-9]{0,3})元"
    r"[（(]大写[：:](?P<capital>[零壹贰叁肆伍陆柒捌玖拾佰仟]{1,12})元整[）)]"
)
_DIGITS = "零壹贰叁肆伍陆柒捌玖"


def _number(value: str) -> int | None:
    digit_pattern = "[一二三四五六七八九]"
    if not re.fullmatch(
        rf"(?:[1-9][0-9]{{0,2}}|{digit_pattern}|{digit_pattern}?十{digit_pattern}?"
        rf"|{digit_pattern}百(?:零{digit_pattern}|{digit_pattern}十{digit_pattern}?)?)",
        value,
    ):
        return None
    if value.isascii():
        return int(value)
    total = digit = 0
    for char in value:
        if char in "十百":
            total += (digit or 1) * {"十": 10, "百": 100}[char]
            digit = 0
        else:
            digit = "零一二三四五六七八九".index(char)
    return total + digit


def _contract(data: RuleInput) -> bool:
    return (
        data.complete_structure
        and len(list(data.prose_matches(_TITLE))) == 1
        and not re.search(r"摘录|节选|示例|模板|另[一份个]*合同", data.text)
        and not any(data.prose_matches(_ATTACHED_CONTRACT))
        and any(data.prose_matches(_CLAUSE))
        and any(
            data.is_prose(match.start(), match.end(2) if match.group(1) else match.end(3))
            for match in _DEFINITION.finditer(data.text)
        )
    )


def _undefined_party(data: RuleInput) -> Iterator[Finding]:
    if not _contract(data):
        return
    defined = {
        match.group(1) or match.group(4)
        for match in _DEFINITION.finditer(data.text)
        if data.is_prose(match.start(), match.end(2) if match.group(1) else match.end(3))
    }
    seen = set()
    for match in data.prose_matches(_PARTY):
        alias = match.group()
        if alias not in defined and alias not in seen:
            seen.add(alias)
            yield Finding(*match.span(), f"本合同中使用了{alias}，未识别到其定义，请人工核对。")


def _missing_clause(data: RuleInput) -> Iterator[Finding]:
    if not _contract(data):
        return
    headings = [_number(match.group(1)) for match in data.prose_matches(_CLAUSE)]
    if None in headings or len(headings) != len(set(headings)):
        return
    defined = set(headings)
    for sentence in re.finditer(r"[^。！？\r\n]+", data.text):
        if re.search(r"《|》|协议|附件|其他|另", sentence.group()):
            continue
        for match in _REFERENCE.finditer(sentence.group()):
            start, end = sentence.start() + match.start(), sentence.start() + match.end()
            number = _number(match.group(1))
            if number is not None and number not in defined and data.is_prose(start, end):
                yield Finding(start, end, "该本合同条款引用未匹配到条款标题，请人工核对编号。")


def _capital_amount(value: int) -> str:
    if value == 0:
        return "零"
    result = ""
    zero = False
    for place, unit in ((1000, "仟"), (100, "佰"), (10, "拾"), (1, "")):
        digit, value = divmod(value, place)
        if digit:
            result += ("零" if zero else "") + _DIGITS[digit] + unit
            zero = False
        elif result and value:
            zero = True
    return result


def _amount_pair(data: RuleInput) -> Iterator[Finding]:
    for match in data.prose_matches(_AMOUNT):
        capital = match.group("capital")
        total = digit = 0
        for char in capital:
            if char in "拾佰仟":
                total += digit * {"拾": 10, "佰": 100, "仟": 1000}[char]
                digit = 0
            else:
                digit = _DIGITS.index(char)
        total += digit
        if total > 9999 or _capital_amount(total) != capital:
            continue
        if int(match.group("number")) != total:
            yield Finding(
                *match.span("capital"),
                "相邻的小写金额与大写金额不一致，请人工核对原文；不判断应采用哪一个金额。",
            )


PROFILE = ScenarioProfile(
    id="legal",
    name="法律文本",
    description="核对合同文本中的明确内部一致性；支持LF/CRLF原文定位，不作法律合规判断。",
    version="2",
    base_checks=(
        "punctuation", "brackets_quotes", "extra_spaces", "number_format",
        "chinese_typos", "variant_chars", "half_full_width", "missing_chars",
        "idiom_misuse", "term_consistency", "grammar_patterns", "repeated_words",
        "english_spelling",
    ),
    extended_checks=("spacing", "extended_english"),
    rules=(
        RuleSpec(
            "scenario.legal.undefined_party", "合同当事方简称核对",
            "仅完整、单一合同标题且存在条款和当事方定义时，"
            "提示义务措辞中未定义的甲乙丙丁方；定义限当事方（可带角色）冒号名称、"
            "名称（当事方）或名称（以下简称当事方），普通提及不算定义。"
            "跳过摘录、模板、引用及实际附件合同标题，不因无关附件提及停用。",
            _undefined_party, requires_complete_structure=True,
        ),
        RuleSpec(
            "scenario.legal.missing_clause", "本合同条款引用核对",
            "仅完整单一合同内的“本合同第N条”与非重复条款标题比较；"
            "使用共享条款标题规则，支持空白、冒号或独立行分隔及三位阿拉伯数字/"
            "简单中文编号；跳过外部法规及歧义范围。",
            _missing_clause, requires_complete_structure=True,
        ),
        RuleSpec(
            "scenario.legal.amount_pair", "相邻大小写金额核对",
            "仅比较0至9999整数元与紧邻括号“大写：…元整”的规范大写金额；"
            "不比较不同付款阶段、分散金额、小数或引文。",
            _amount_pair,
        ),
    ),
    semantic_guidance=(
        "仅依照本次提供的法律文本核对当事方、条款引用和同一义务的明确内部矛盾。"
        "区分主合同、附件、引用法规及不同履行阶段；证据或范围不明确时不报错。"
        "抽样片段不能证明定义或条款缺失，不补造未提供的信息。"
        "不联网核法、不提供法律意见、不作效力或合规结论；全部建议仅供人工核对，"
        "保留规范法律措辞，不自动替换。"
    ),
)
