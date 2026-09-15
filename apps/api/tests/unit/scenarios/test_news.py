import importlib
import importlib.util

import pytest

from text_verification.scenarios.models import RuleInput


def check(name, text):
    module = "text_verification.scenarios.news"
    assert importlib.util.find_spec(module) is not None, "news package is not implemented"
    profile = importlib.import_module(module).PROFILE
    rule = next(rule for rule in profile.rules if rule.rule_id == f"scenario.news.{name}")
    return list(rule.check(RuleInput(text)))


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_headline_lead_identical_event_metric_counts(newline):
    text = "📰\n标题：青山地震造成3人受伤\n导语：青山地震造成5人受伤。\n".replace("\n", newline)
    findings = check("headline_count", text)
    assert len(findings) == 1
    assert text[findings[0].start:findings[0].end] == "5"
    assert findings[0].start == text.index("5")


@pytest.mark.parametrize("text", [
    "标题：青山地震造成3人受伤\n导语：青山地震造成3人受伤。",
    "标题：青山地震造成3人受伤\n导语：白云地震造成5人受伤。",
    "标题：青山地震造成3人死亡\n导语：青山地震造成5人受伤。",
    "标题：青山地震造成3人受伤\n导语：截至今日青山地震造成5人受伤。",
    "标题：青山地震造成3人受伤\n导语：青山地震造成5人受伤，另有2人失踪。",
    "标题：青山地震造成3人受伤\n导语：青山地震造成5人受伤。\n标题：另一事件",
    "```\n标题：青山地震造成3人受伤\n导语：青山地震造成5人受伤。\n```",
    "标题：“青山地震造成3人受伤”\n导语：青山地震造成5人受伤。",
])
def test_headline_count_never_compares_different_or_ambiguous_events(text):
    assert check("headline_count", text) == []


@pytest.mark.parametrize("headline,lead", [
    ("青山新增3家企业", "青山新增5家企业。"),
    ("青山新建3所学校", "青山新建5所学校。"),
    ("青山共有3家医院", "青山共有5家医院。"),
    ("青山新建3座桥梁", "青山新建5座桥梁。"),
])
def test_headline_count_supports_explicit_ordinary_quantities(headline, lead):
    text = f"📰\n标题：{headline}\n导语：{lead}"
    findings = check("headline_count", text)
    assert len(findings) == 1
    assert text[findings[0].start:findings[0].end] == "5"


@pytest.mark.parametrize("headline,lead", [
    ("青山新增3家企业", "青山新增3家企业。"),
    ("青山新增3家企业", "白云新增5家企业。"),
    ("青山新增3家企业", "青山共有5家企业。"),
    ("青山新建3所学校", "青山新建5家医院。"),
    ("青山新增3家企业", "截至今日青山新增5家企业。"),
    ("青山新增约3家企业", "青山新增约5家企业。"),
    ("预计青山新增3家企业", "预计青山新增5家企业。"),
    ("青山计划新建3所学校", "青山计划新建5所学校。"),
    ("青山可能新增3家企业", "青山可能新增5家企业。"),
    ("青山并未新增3家企业", "青山并未新增5家企业。"),
    ("青山新增3家企业左右", "青山新增5家企业左右。"),
    ("青山新增3余家企业", "青山新增5余家企业。"),
    ("青山新增3至4家企业", "青山新增5至6家企业。"),
    ("青山新增3.5家企业", "青山新增5.5家企业。"),
    ("2024年青山新增3家企业", "2024年青山新增5家企业。"),
    ("２０２４年青山新增3家企业", "２０２４年青山新增5家企业。"),
    ("三月青山新增3家企业", "三月青山新增5家企业。"),
    ("白云新增三家企业，青山新增3家企业", "白云新增三家企业，青山新增5家企业。"),
    ("青山新增3家企业，创造2个岗位", "青山新增5家企业，创造2个岗位。"),
    ("青山新增3家高新企业", "青山新增5家高新企业。"),
    ("“青山新增3家企业”", "青山新增5家企业。"),
])
def test_ordinary_counts_require_one_exact_unqualified_statement(headline, lead):
    assert check("headline_count", f"标题：{headline}\n导语：{lead}") == []


def test_ordinary_counts_skip_code_literals():
    text = "```\n标题：青山新增3家企业\n导语：青山新增5家企业。\n```"
    assert check("headline_count", text) == []


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_relative_date_uses_document_date_and_unicode_offsets(newline):
    text = "📰\n发布日期：2024年3月1日\n昨日（2024年2月28日）召开会议。\n".replace("\n", newline)
    findings = check("relative_date", text)
    assert len(findings) == 1
    assert text[findings[0].start:findings[0].end] == "昨日（2024年2月28日）"
    assert findings[0].start == text.index("昨日")


@pytest.mark.parametrize("text", [
    "发布日期：2024年3月1日\n昨日（2024年2月29日）召开会议。",
    "发布日期：2024-03-01\n明日（2024年3月2日）召开会议。",
    "昨日（2024年2月28日）召开会议。",
    "发布日期：2024年3月1日\n昨日召开会议；2024年2月28日开始报名。",
    "发布日期：2024年3月1日\n“昨日（2024年2月28日）召开会议。”",
    "发布日期：2024年3月1日\n发布日期：2024年2月29日\n昨日（2024年2月28日）",
    "发布日期：2024年2月30日\n昨日（2024年2月28日）",
    "发布日期：2024年3月1日\n昨日（2024年2月30日）",
    "发布日期：2024年3月1日\n```\n昨日（2024年2月28日）\n```",
])
def test_relative_date_ignores_missing_invalid_or_ambiguous_anchors(text):
    assert check("relative_date", text) == []


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_vague_source_is_only_an_information_prompt(newline):
    text = "📰\n有数据显示，参与人数增长。\n".replace("\n", newline)
    findings = check("vague_source", text)
    assert len(findings) == 1
    assert text[findings[0].start:findings[0].end] == "有数据显示"
    assert findings[0].start == text.index("有数据显示")
    assert findings[0].severity == "info"


@pytest.mark.parametrize("text", [
    "据统计局发布的数据，人数增长。",
    "据统计，人数增长（来源：市政府）。",
    "有数据显示，人数增长，数据来自青山大学。",
    "根据市政府报告，据统计，人数增长。",
    "他说：“据统计，人数增长。”",
    "```\n据统计，人数增长。\n```",
    "`有数据显示`是示例措辞。",
])
def test_source_prompt_respects_same_sentence_attribution_and_literals(text):
    assert check("vague_source", text) == []


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
@pytest.mark.parametrize("sentence", [
    "有数据显示，事故涉及两家公司。",
    "有数据显示，事故发生在大学附近。",
    "有数据显示，报告数量增长。",
    "有数据显示，调查仍在进行。",
    "有数据显示，参与者来自两家公司。",
    "有数据显示，消息来源尚不明确。",
    "有数据显示，当地发布招聘信息。",
])
def test_organization_and_report_mentions_are_not_source_attribution(sentence, newline):
    text = ("📰\n" + sentence).replace("\n", newline)
    findings = check("vague_source", text)
    assert len(findings) == 1
    assert text[findings[0].start:findings[0].end] == "有数据显示"
    assert findings[0].severity == "info"


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
@pytest.mark.parametrize("sentence", [
    "据青山大学发布的数据，有数据显示，参与人数增长。",
    "根据市政府报告，有数据显示，参与人数增长。",
    "有数据显示，参与人数增长（来源：市政府）。",
    "有数据显示，参与人数增长，数据来自青山大学。",
    "有数据显示，参与人数增长，数据来源于市统计局。",
    "有数据显示，来自青山大学的报告记录了增长。",
])
def test_explicit_source_relations_suppress_only_the_source_prompt(sentence, newline):
    assert check("vague_source", ("📰\n" + sentence).replace("\n", newline)) == []


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
@pytest.mark.parametrize("anchor", [
    "以下以2024年2月29日为叙述基准：",
    "下文以2024年2月29日为时间基准：",
    "叙述基准：2024年2月29日",
    "下文日期以2024年2月29日为准。",
])
def test_relative_dates_skip_explicit_alternative_narration_bases(anchor, newline):
    text = "发布日期：2024年3月1日\n" + anchor + "\n昨日（2024年2月28日）召开会议。"
    assert check("relative_date", text.replace("\n", newline)) == []


@pytest.mark.parametrize("literal", [
    "“以下以2024年2月29日为叙述基准：”",
    "```\n以下以2024年2月29日为叙述基准：\n```",
])
def test_quoted_or_code_time_basis_does_not_override_prose_date(literal):
    text = "发布日期：2024年3月1日\n" + literal + "\n昨日（2024年2月28日）召开会议。"
    findings = check("relative_date", text)
    assert len(findings) == 1
    assert text[findings[0].start:findings[0].end] == "昨日（2024年2月28日）"
