from __future__ import annotations

import re
from collections.abc import Iterable

from text_verification.compatibility.text_context import (
    ABBREVIATION_DEFINITION_PATTERN as _DEFINITION,
)

from .models import Finding, RuleInput, RuleSpec, ScenarioProfile

_REFERENCES = re.compile(r"[ \t]*(?:#{1,6}[ \t]+)?(?:参考文献|References)[:：]?[ \t\r]*", re.I)
_ENTRY = re.compile(r"[ \t]*\[(?P<number>[1-9][0-9]{0,3})\][ \t]+\S[^\n]*")
_CITATION = re.compile(
    r"(?<![\[\]])(?P<citation>\[(?P<number>[1-9][0-9]{0,3})\])(?![\[\]])"
)
_CITATION_CUE = re.compile(r"(?:文献|参见|\bsee|\breferences?)[ \t]*$", re.I)
_BRACKET_SYNTAX = re.compile(r"[ \t]*[\[(\]:=]")
_NARRATIVE = re.compile(r"(?<![\u4e00-\u9fff])[\u4e00-\u9fff]{4,120}[ \t]*$")
_RESEARCH_SUBJECT = re.compile(r"研究|结果|实验|分析|证据|调查")
_RESEARCH_STATEMENT = re.compile(r"表明|显示|证明|证实|发现|指出|提出|支持|验证")
_AMBIGUOUS_CITATION = re.compile(r"数组|矩阵|向量|索引|下标|元素|列表|编号|示例|假设|假定|占位")
_SENTENCE_END = re.compile(r"[ \t]*[。！？.!?]")
_CAPTION_PREFIX = re.compile(
    r"[ \t]*(?P<kind>图|表|Figure|Table)[ \t]*(?P<number>[1-9][0-9]{0,3})", re.I
)
_CAPTION = re.compile(
    r"[ \t]*(?P<kind>图|表|Figure|Table)[ \t]*(?P<number>[1-9][0-9]{0,3})"
    r"(?:[ \t]*[:：][ \t]*|[.][ \t]+|[ \t]+)\S[^\n]*",
    re.I,
)
_LOCAL_REFERENCE = re.compile(
    r"(?P<cn>本文(?P<cn_kind>图|表)[ \t]*(?P<cn_number>[1-9][0-9]{0,3}))"
    r"(?![0-9A-Za-z.(（\-])"
    r"|\bsee[ \t]+(?P<en>(?P<en_kind>Figure|Table)[ \t]+"
    r"(?P<en_number>[1-9][0-9]{0,3}))[ \t]+in this (?:paper|document|report)\b",
    re.I,
)
_KINDS = {"图": "figure", "figure": "figure", "表": "table", "table": "table"}
_ALTERNATIVE = re.compile(r"或|又称|亦称|\b(?:or|aka|also)\b", re.I)


def citation_reference(data: RuleInput) -> Iterable[Finding]:
    if not data.complete_structure:
        return
    lines = list(data.lines())
    headings = [
        index
        for index, (start, end, line) in enumerate(lines)
        if _REFERENCES.fullmatch(line) and data.is_prose(start, end)
    ]
    if len(headings) != 1:
        return
    heading = headings[0]
    numbers = set()
    for start, _, line in lines[heading + 1:]:
        if not line.strip():
            continue
        entry = _ENTRY.fullmatch(line)
        if not entry or not data.is_prose(start, start + entry.end("number")):
            return
        number = entry["number"]
        if number in numbers:
            return
        numbers.add(number)
    if not numbers:
        return
    for start, _, line in lines[:heading]:
        if line.lstrip().startswith(">"):
            continue
        for match in _CITATION.finditer(line):
            if _BRACKET_SYNTAX.match(line, match.end()):
                continue
            prefix = line[max(0, match.start() - 160):match.start()]
            if not _CITATION_CUE.search(prefix):
                narrative = _NARRATIVE.search(prefix)
                if (
                    not narrative
                    or not _SENTENCE_END.match(line, match.end())
                    or not _RESEARCH_SUBJECT.search(narrative[0])
                    or not _RESEARCH_STATEMENT.search(narrative[0])
                    or _AMBIGUOUS_CITATION.search(narrative[0])
                ):
                    continue
            if match["number"] not in numbers and data.is_prose(
                start + match.start(), start + match.end()
            ):
                yield Finding(
                    start + match.start("citation"),
                    start + match.end("citation"),
                    f"明确引用的编号 {match['number']} 未见于本文末尾的编号参考文献，请人工核对。",
                )


def caption_reference(data: RuleInput) -> Iterable[Finding]:
    if not data.complete_structure:
        return
    lines = list(data.lines())
    captions: dict[str, set[str]] = {"figure": set(), "table": set()}
    ambiguous = set()
    for start, _, line in lines:
        prefix = _CAPTION_PREFIX.match(line)
        if not prefix or not data.is_prose(start, start + prefix.end()):
            continue
        kind = _KINDS[prefix["kind"].lower()]
        caption = _CAPTION.fullmatch(line)
        if not caption or caption["number"] in captions[kind]:
            ambiguous.add(kind)
        else:
            captions[kind].add(caption["number"])
    for start, _, line in lines:
        if line.lstrip().startswith(">"):
            continue
        for match in _LOCAL_REFERENCE.finditer(line):
            kind = _KINDS[(match["cn_kind"] or match["en_kind"]).lower()]
            number = match["cn_number"] or match["en_number"]
            if kind in ambiguous or not captions[kind] or number in captions[kind]:
                continue
            if not data.is_prose(start + match.start(), start + match.end()):
                continue
            group = "cn" if match["cn"] else "en"
            yield Finding(
                start + match.start(group),
                start + match.end(group),
                "明确指向本文的图表编号未见对应题注，请人工核对；不推断外部文献的图表。",
            )


def abbreviation_definition(data: RuleInput) -> Iterable[Finding]:
    definitions: dict[tuple[str, str], str] = {}
    previous_end = -1
    glossary = {term.casefold() for term in data.glossary_terms}
    for start, end, line in data.lines():
        if start > previous_end + 1:
            definitions.clear()
        previous_end = end
        match = _DEFINITION.fullmatch(line)
        if not match or not data.is_prose(start, end) or _ALTERNATIVE.search(match["meaning"]):
            definitions.clear()
            continue
        abbreviation = match["abbr"]
        meaning = " ".join(match["meaning"].casefold().split())
        if abbreviation.casefold() in glossary or meaning in glossary:
            definitions.clear()
            continue
        if re.fullmatch(r"[\u4e00-\u9fff \-]+", meaning):
            language = "zh"
        elif re.fullmatch(r"[a-z \-]+", meaning):
            language = "en"
        else:
            # Mixed expansions neither contradict nor overwrite monolingual evidence.
            continue
        key = (abbreviation, language)
        previous = definitions.get(key)
        if previous and previous != meaning:
            yield Finding(
                start + match.start("meaning"),
                start + match.end("meaning"),
                f"同一连续定义块内缩写 {abbreviation} 出现不同的同语种释义，请人工确认。",
            )
        definitions[key] = meaning


PROFILE = ScenarioProfile(
    id="academic",
    version="2",
    name="学术论文",
    description="保守核对明确编号引用、本文图表题注与连续缩写定义，不评判研究事实或完整性。",
    base_checks=(
        "punctuation", "brackets_quotes", "extra_spaces", "number_format", "chinese_typos",
        "variant_chars", "half_full_width", "missing_chars", "idiom_misuse", "term_consistency",
        "expression_issues", "grammar_patterns", "repeated_words", "english_spelling",
    ),
    extended_checks=("spacing", "extended_english"),
    rules=(
        RuleSpec(
            rule_id="scenario.academic.citation_reference",
            name="明确引文编号与文末参考文献对应",
            description=(
                "仅完整文本中唯一的“参考文献/References”末节，逐行 [整数] 条目且编号唯一时，"
                "核对正文“文献/参见/see/reference(s) [整数]”，或4–120字纯中文研究叙述"
                "（含研究/结果/实验/分析/证据/调查及表明/显示等报告动词）句末的[整数]。"
                "跳过数组/索引等歧义语境、假设示例、嵌套括号、链接、代码、引语、"
                "重复编号、混合格式和非编号末节；不查未引用条目、组合编号或外部文献。"
            ),
            check=citation_reference,
            requires_complete_structure=True,
        ),
        RuleSpec(
            rule_id="scenario.academic.caption_reference",
            name="明确本文图表引用与题注对应",
            description=(
                "仅完整文本中“本文图/表N”或“see Figure/Table N in this paper/document/report”，"
                "对照行首“图/表/Figure/Table N: 标题”（亦接受空白或英文点号加空格分隔）；"
                "同类题注至少一个且无重复或复杂编号才检查；不核对外部引用、分图或节编号。"
            ),
            check=caption_reference,
            requires_complete_structure=True,
        ),
        RuleSpec(
            rule_id="scenario.academic.abbreviation_definition",
            name="连续显式缩写定义冲突",
            description=(
                "仅连续行“缩写/Abbreviation ABC: 释义”，2–10位大写字母缩写的单语同语种释义"
                "不一致时提示；空行或其他行终止作用域，忽略大小写及空格差异、术语表豁免、"
                "含或/or/又称的别名、代码与引语。混合中英释义不建立冲突或覆盖已有单语释义；"
                "不猜测首次使用缺定义，不推断中英翻译关系。"
            ),
            check=abbreviation_definition,
        ),
    ),
    semantic_guidance=(
        "面向中文学术文本，优先检查作者明确写出的研究对象、方法、论证及术语是否前后一致。"
        "仅依据当前文本指出有明确证据的表述问题，不借外部知识判断研究真伪或编造引文。"
        "摘录、DOCX/PDF/OCR结构不完整时，不臆测缺失的参考文献、图表、定义或章节。"
        "保留学科惯用缩写、公式、代码和被引用的原话；不强行口语改写，不作学术合规认证。"
        "专业建议均需人工确认，不自动替换。"
    ),
)
