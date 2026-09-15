from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import date, timedelta

from .models import Finding, RuleInput, RuleSpec, ScenarioProfile

_HEADLINE = re.compile(r"^[ \t]*标题[：:](?P<text>[^\r\n]+)\r?$", re.M)
_LEAD = re.compile(r"^[ \t]*导语[：:](?P<text>[^\r\n]+)\r?$", re.M)
_COUNT = re.compile(
    r"(?P<event>[^。！？，；：、（）()\n\d]{1,80}(?:造成|导致|共有|共|新增|新建))"
    r"(?P<count>[0-9]{1,9})"
    r"(?P<metric>人(?:受伤|死亡|失踪)|家企业|所学校|家医院|座桥梁)[。！]?"
)
_COUNT_QUALIFIER = re.compile(
    r"预计|预期|预测|估计|估算|计划|规划|拟|可能|或|将|有望|力争|争取|"
    r"约|近|至少|至多|最多|不少于|不超过|超过|不足|未|不|没有|"
    r"[零〇一二三四五六七八九十百千万亿两]+(?:年|月|日|家|所|座|人|个|次|项|台|辆)"
)
_DATE = r"([0-9]{4})(?:年|-)([0-9]{1,2})(?:月|-)([0-9]{1,2})日?"
_DOCUMENT_DATE = re.compile(r"^[ \t]*发布日期[：:][ \t]*" + _DATE + r"[ \t]*\r?$", re.M)
_RELATIVE = re.compile(r"(今日|昨日|明日)[（(]" + _DATE + r"[）)]")
_TIME_BASIS = re.compile(
    r"(?:以|按)[^。！？\r\n]{1,60}(?:为|作为)(?:(?:叙述|叙事|时间|日期|报道)?基准|准)"
    r"|(?:叙述|叙事|时间|日期)(?:基准|参照)[：:]"
)
_VAGUE = re.compile(r"据统计(?!局)|有数据显示")
_SOURCE = re.compile(
    r"(?:数据|统计|信息|消息|资料)(?:来自|来源于|来源[：:])[ \t]*"
    r"[^\s，,。！？；;（）()\r\n：:]{1,60}"
    r"|(?:^|[（(，,；;])[ \t]*来源[：:][ \t]*[^\s，,。！？；;（）()\r\n：:]{1,60}"
    r"|(?:根据|据)[ \t]*[^，,。！？；;（）()\r\n]{1,60}(?:发布|公布|报告|调查|统计|数据)"
    r"|(?:来自|出自)[^，,。！？；;（）()\r\n]{1,60}的(?:数据|统计|报告|调查)"
)


def _headline_count(data: RuleInput) -> Iterator[Finding]:
    headlines = list(_HEADLINE.finditer(data.text))
    leads = list(_LEAD.finditer(data.text))
    if len(headlines) != 1 or len(leads) != 1:
        return
    headline, lead = headlines[0], leads[0]
    if not data.is_prose(*headline.span()) or not data.is_prose(*lead.span()):
        return
    left = _COUNT.fullmatch(headline.group("text").strip())
    right = _COUNT.fullmatch(lead.group("text").strip())
    if not left or not right:
        return
    if _COUNT_QUALIFIER.search(left.group("event")) or _COUNT_QUALIFIER.search(
        right.group("event")
    ):
        return
    if (left.group("event"), left.group("metric")) != (
        right.group("event"), right.group("metric"),
    ):
        return
    if int(left.group("count")) != int(right.group("count")):
        offset = lead.start("text") + len(lead.group("text")) - len(
            lead.group("text").lstrip()
        )
        yield Finding(
            offset + right.start("count"), offset + right.end("count"),
            "标题与导语中相同事件、相同指标的数量不一致，请人工核对统计口径及原文。",
        )


def _relative_date(data: RuleInput) -> Iterator[Finding]:
    anchors = list(data.prose_matches(_DOCUMENT_DATE))
    if len(anchors) != 1 or any(data.prose_matches(_TIME_BASIS)):
        return
    try:
        published = date(*(int(value) for value in anchors[0].groups()))
    except ValueError:
        return
    for match in data.prose_matches(_RELATIVE):
        try:
            absolute = date(*(int(value) for value in match.groups()[1:]))
            expected = published + timedelta(days={"今日": 0, "昨日": -1, "明日": 1}[match[1]])
        except (ValueError, OverflowError):
            continue
        if absolute != expected:
            yield Finding(
                *match.span(),
                "相对日期所附的绝对日期与本文发布日期不一致，请人工确认叙述时间基准。",
            )


def _vague_source(data: RuleInput) -> Iterator[Finding]:
    for sentence in re.finditer(r"[^。！？\r\n]+", data.text):
        if not data.is_prose(*sentence.span()):
            continue
        if _SOURCE.search(_VAGUE.sub("", sentence.group())):
            continue
        for match in _VAGUE.finditer(sentence.group()):
            yield Finding(
                sentence.start() + match.start(), sentence.start() + match.end(),
                "本句使用笼统数据引述，未识别到明确来源；请人工确认是否需要补充署名或出处。",
                severity="info", confidence=0.7,
            )


PROFILE = ScenarioProfile(
    id="news",
    name="新闻稿件",
    description="核对稿件内明确数量、日期与数据出处；支持LF/CRLF原文定位。",
    version="2",
    base_checks=(
        "punctuation", "brackets_quotes", "extra_spaces", "number_format",
        "chinese_typos", "variant_chars", "half_full_width", "missing_chars",
        "idiom_misuse", "term_consistency", "expression_issues", "grammar_patterns",
        "repeated_words", "english_spelling",
    ),
    extended_checks=("spacing", "extended_english"),
    rules=(
        RuleSpec(
            "scenario.news.headline_count", "标题导语数量核对",
            "仅单一显式“标题：/导语：”的整句事件措辞及指标完全相同，"
            "且仅一处1至9位阿拉伯整数数量不同时提示。"
            "限造成/导致/共有/共/新增/新建及人受伤/人死亡/人失踪/家企业/所学校/"
            "家医院/座桥梁；跳过数量修饰、计划预测否定措辞、其他数字及复合分句，"
            "不比较不同事件、时段或措辞。",
            _headline_count,
        ),
        RuleSpec(
            "scenario.news.relative_date", "稿件相对日期核对",
            "仅单一显式发布日期与今日/昨日/明日紧邻括号内完整年月日比较；"
            "不使用机器日期；存在另行指定的叙述/时间基准时跳过日期比较，"
            "并跳过无锚点、无效日期和引文。",
            _relative_date,
        ),
        RuleSpec(
            "scenario.news.vague_source", "笼统数据来源提示",
            "仅“据统计/有数据显示”所在句没有识别到明确归属关系时作info级人工提示；"
            "限数据来自/来源于、来源标签、据或根据某来源发布/报告等关系，"
            "不把公司、大学、报告等普通名词当作来源；跳过含引文或代码的句子，"
            "不认定数据失实或全文缺少来源。",
            _vague_source,
        ),
    ),
    semantic_guidance=(
        "只核对本次稿件提供的标题、导语、日期及归属明确的来源线索。"
        "数量必须属于同一事件、指标、时间点及统计口径；相对时间只依显式稿件日期，"
        "不用当前日期推断。尊重直接引语，不把引语与记者叙述混为一谈。"
        "来源不明只作人工补充提示，不断言虚假新闻；不外部核实、不作合规结论。"
        "抽样片段不能证明全文缺少背景或出处，不编造缺失事实，所有建议均人工处理。"
    ),
)
