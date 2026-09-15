from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date
from decimal import Decimal, localcontext

from .models import Finding, RuleInput, RuleSpec, ScenarioProfile

_AMOUNT_HEADER = re.compile(
    r"[ \t]*(?:金额明细(?:（完整）)?|Amount breakdown(?: \(complete\))?)[ \t\r]*", re.I
)
_AMOUNT_ROW = re.compile(
    r"[ \t]*(?:(?P<bullet>-[ \t]+)(?P<label>[^:：\n]{1,80})|(?P<total>合计|Total))"
    r"[ \t]*[:：][ \t]*(?P<amount>[^\n]{1,50}?)[ \t\r]*",
    re.I,
)
_AMOUNT = re.compile(
    r"(?:(?P<prefix>CNY|RMB|USD|EUR|人民币)[ \t]*)?"
    r"(?P<number>(?:0|[1-9][0-9]{0,17})(?:\.[0-9]{1,2})?)"
    r"[ \t]*(?P<suffix>元|美元|欧元)?",
    re.I,
)
_CURRENCIES = {
    "cny": "CNY", "rmb": "CNY", "人民币": "CNY", "元": "CNY",
    "usd": "USD", "美元": "USD", "eur": "EUR", "欧元": "EUR",
}
_ADJUSTMENT = re.compile(
    r"税|小计|合计|折扣|优惠|单价|数量|比例|subtotal|total|tax|vat|discount|quantity|rate",
    re.I,
)
_PROJECT = re.compile(r"[ \t]*(?:项目|Project)[ \t]*[:：][ \t]*\S[^\n]*", re.I)
_PROJECT_METADATA = re.compile(
    r"[ \t]*(?:负责人|Owner)[ \t]*[:：][ \t]*[^:：;；\r\n]{1,80}[ \t\r]*", re.I
)
_DATE = re.compile(
    r"[ \t]*(?P<label>开始日期|结束日期|Start date|End date)[ \t]*[:：][ \t]*"
    r"(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2}|[0-9]{4}年[0-9]{1,2}月[0-9]{1,2}日)"
    r"[ \t\r]*",
    re.I,
)
_TASK_HEADER = re.compile(
    r"[ \t]*(?:#{1,6}[ \t]+)?(?:待办事项|行动项|Action items|Tasks)[:：]?[ \t\r]*", re.I
)
_TASK = re.compile(
    r"[ \t]*-[ \t]+(?:\[ \][ \t]+)?(?:任务|行动|Task|Action)[ \t]*[:：][ \t]*"
    r"(?P<task>[^;；\n]{1,200}?)[ \t]*[;；][ \t]*(?:截止|Deadline)[ \t]*[:：][ \t]*"
    r"(?P<deadline>[^;；\n]{1,100}?)(?:[ \t]*[;；][ \t]*"
    r"(?:负责人|Owner)[ \t]*[:：][ \t]*(?P<owner>[^;；\n]{1,80}?))?[ \t\r]*",
    re.I,
)
_VAGUE = {"尽快", "尽早", "待定", "近期", "asap", "soon", "tbd"}
_COMPLETED_TASK = re.compile(r"[ \t]*-[ \t]+\[[xX]\][ \t]+\S[^\r\n]*[ \t\r]*")


def line_item_total(data: RuleInput) -> Iterable[Finding]:
    if not data.complete_structure:
        return
    active = False
    amounts: list[Decimal] = []
    labels: set[str] = set()
    currency = None
    previous_end = -1
    lines = list(data.lines())
    for index, (start, end, line) in enumerate(lines):
        if start > previous_end + 1:
            active = False
        previous_end = end
        if _AMOUNT_HEADER.fullmatch(line) and data.is_prose(start, end):
            active, amounts, labels, currency = True, [], set(), None
            continue
        if not active:
            continue
        row = _AMOUNT_ROW.fullmatch(line)
        if not row or not data.is_prose(start, end):
            active = False
            continue
        amount = _AMOUNT.fullmatch(row["amount"])
        if not amount or bool(amount["prefix"]) == bool(amount["suffix"]):
            active = False
            continue
        row_currency = _CURRENCIES[(amount["prefix"] or amount["suffix"]).lower()]
        if currency is not None and row_currency != currency:
            active = False
            continue
        currency = row_currency
        value = Decimal(amount["number"])
        if row["bullet"]:
            label = row["label"].strip().casefold()
            if label in labels or _ADJUSTMENT.search(label) or len(amounts) >= 1000:
                active = False
                continue
            labels.add(label)
            amounts.append(value)
        else:
            active = False
            if len(amounts) < 2:
                continue
            if index + 1 < len(lines):
                next_start, _, next_line = lines[index + 1]
                if next_start == end + 1 and next_line.strip():
                    continue
            with localcontext() as context:
                context.prec = 40
                expected = sum(amounts, Decimal(0))
            if value != expected:
                number_start = start + row.start("amount") + amount.start("number")
                yield Finding(
                    number_start,
                    number_start + len(amount["number"]),
                    f"完整金额明细逐项相加为 {expected} {currency}，与合计不符，请人工核对。",
                )


def date_order(data: RuleInput) -> Iterable[Finding]:
    dates: dict[str, tuple[date, int, int]] = {}
    active = False
    previous_end = -1
    # A sentinel closes the final project block without a second parsing pass.
    for start, end, line in (*data.lines(), (len(data.text) + 2, len(data.text) + 2, "")):
        project = bool(_PROJECT.fullmatch(line)) and data.is_prose(start, end)
        boundary = start > previous_end + 1 or not line.strip() or project
        if boundary:
            if active and "start" in dates and "end" in dates:
                begin, finish = dates["start"], dates["end"]
                if begin[0] > finish[0]:
                    yield Finding(
                        finish[1], finish[2],
                        "同一项目块内明确标注的结束日期早于开始日期，请人工核对日期或标签。",
                    )
            active, dates = False, {}
        previous_end = end
        if project:
            active = True
            continue
        if not active:
            continue
        if _PROJECT_METADATA.fullmatch(line) and data.is_prose(start, end):
            continue
        match = _DATE.fullmatch(line)
        if not match or not data.is_prose(start, end):
            active = False
            continue
        key = "start" if match["label"].lower() in {"开始日期", "start date"} else "end"
        if key in dates:
            active = False
            continue
        parts = re.findall(r"[0-9]+", match["date"])
        try:
            parsed = date(*(int(part) for part in parts))
        except ValueError:
            active = False
            continue
        dates[key] = (parsed, start + match.start("date"), start + match.end("date"))


def action_clarity(data: RuleInput) -> Iterable[Finding]:
    if not data.complete_structure:
        return
    active = False
    previous_end = -1
    for start, end, line in data.lines():
        if start > previous_end + 1:
            active = False
        previous_end = end
        if _TASK_HEADER.fullmatch(line) and data.is_prose(start, end):
            active = True
            continue
        if not active:
            continue
        if _COMPLETED_TASK.fullmatch(line):
            continue
        match = _TASK.fullmatch(line)
        if not match or not data.is_prose(start, end):
            active = False
            continue
        if match["deadline"].casefold() in _VAGUE:
            yield Finding(
                start + match.start("deadline"),
                start + match.end("deadline"),
                "行动清单中的截止字段只有模糊时间，请人工确认是否需要明确可核验的期限。",
            )
        if not match["owner"]:
            yield Finding(
                start + match.start("task"),
                start + match.end("task"),
                "行动清单此任务行未列负责人字段，请人工确认是否需补充或由清单外统一指定。",
                severity="info",
            )


PROFILE = ScenarioProfile(
    id="business",
    version="2",
    name="商务公文",
    description="核对显式完整金额清单、项目起止日期及行动清单字段，不对一般叙述施加任务格式。",
    base_checks=(
        "punctuation", "brackets_quotes", "extra_spaces", "number_format", "chinese_typos",
        "variant_chars", "half_full_width", "missing_chars", "idiom_misuse", "term_consistency",
        "expression_issues", "grammar_patterns", "repeated_words", "english_spelling",
    ),
    extended_checks=("spacing", "extended_english"),
    rules=(
        RuleSpec(
            rule_id="scenario.business.line_item_total",
            name="显式完整金额清单合计",
            description=(
                "仅完整文本中“金额明细/Amount breakdown”（可带完整标记）后连续2–1000条"
                "“- 名称: 金额”及“合计/Total: 金额”，合计后空行或文末；"
                "同币种CNY/RMB/人民币/元、USD/美元、EUR/欧元，非负18位内整数及至多2位小数。"
                "Decimal精确相加；跳过重复名称、税费/折扣/小计/数量/单价、混合币种、"
                "倍率单位、裸货币符号、代码与引语；合计后同块其他行或多重合计均跳过。"
            ),
            check=line_item_total,
            requires_complete_structure=True,
        ),
        RuleSpec(
            rule_id="scenario.business.date_order",
            name="同项目显式起止日期倒置",
            description=(
                "仅“项目/Project: 名称”后同一连续块内各一次“开始日期/Start date”与"
                "“结束日期/End date”，日期为有效YYYY-MM-DD或YYYY年M月D日；"
                "允许前后或中间有独立负责人/Owner字段；空行或新项目分隔作用域，"
                "其余字段、尾注、重复日期标签、无效日期、代码及引语均使本块跳过。"
                "仅核对本地日期顺序，不比较跨项目日期或推算工期。"
            ),
            check=date_order,
        ),
        RuleSpec(
            rule_id="scenario.business.action_clarity",
            name="显式行动清单期限与负责人",
            description=(
                "仅完整文本“待办事项/行动项/Action items/Tasks”后连续未完成的“-”条目，"
                "且逐行显式“任务/Task: 内容；截止/Deadline: 时间[；负责人/Owner: 人名]”；"
                "期限恰为尽快/尽早/待定/近期/ASAP/soon/TBD时提示，缺负责人字段给人工信息提示。"
                "已完成的[x]/[X]条目不检查且不中断后续待办；空行、其他字段或行终止清单。"
                "跳过普通叙述、代码和引语，不猜测责任人。"
            ),
            check=action_clarity,
            requires_complete_structure=True,
        ),
    ),
    semantic_guidance=(
        "面向中文商务文本，仅根据文内明确陈述核对金额、起止时间、交付动作及责任表述。"
        "保留合同引用、产品术语与代码示例；任务清晰度要求仅用于明确行动清单，不扩散至一般叙述。"
        "不假定税率、汇率、隐含小计或业务事实，不据摘录或缺页推断缺少条款、人员或交付内容。"
        "对责任归属、日期和金额的提示必须供人工核实，不自动替换、不提供合规认证。"
    ),
)
