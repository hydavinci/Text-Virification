import importlib
import importlib.util

import pytest

from text_verification.scenarios.models import RuleInput


def check(rule, text, *, complete=True):
    module = "text_verification.scenarios.business"
    assert importlib.util.find_spec(module) is not None, "business package is not implemented"
    profile = importlib.import_module(module).PROFILE
    spec = next(item for item in profile.rules if item.rule_id == f"scenario.business.{rule}")
    return list(spec.check(RuleInput(text, complete)))


def assert_hit(findings, text, fragment, *, last=False):
    start = text.rindex(fragment) if last else text.index(fragment)
    assert [(item.start, item.end) for item in findings] == [(start, start + len(fragment))]
    assert text[findings[0].start:findings[0].end] == fragment
    assert findings[0].description


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("😀预算\n金额明细（完整）\n- 设计：10.10元\n- 开发：20.20元\n合计：31.00元", "31.00"),
        (
            "Amount breakdown (complete)\n- Design: USD 0.10\n- Build: USD 0.20\nTotal: USD 0.31",
            "0.31",
        ),
        ("金额明细（完整）\n- 设计：CNY 10\n- 开发：人民币20\n合计：RMB 40", "40"),
    ],
)
def test_explicit_amount_only_total_mismatch(text, fragment):
    assert_hit(check("line_item_total", text), text, fragment, last=True)


@pytest.mark.parametrize(
    "text",
    [
        "金额明细（完整）\n- 设计：0.10元\n- 开发：0.20元\n合计：0.30元",
        "金额明细（完整）\n- 设计：10元\n- 开发：20美元\n合计：40元",
        "金额明细（完整）\n- 设计：10万元\n- 开发：20元\n合计：40元",
        "金额明细（完整）\n- 设计：10元/小时\n- 开发：20元\n合计：40元",
        "金额明细（完整）\n- 设计：10元\n- 税费：20元\n合计：40元",
        "金额明细（完整）\n- 设计：10元\n- 小计：20元\n合计：40元",
        "金额明细（完整）\n- 设计：10元\n\n- 开发：20元\n合计：40元",
        "金额明细（完整）\n- 设计：10元\n- 设计：20元\n合计：40元",
        "金额明细（完整）\n- 设计：10元\n合计：40元",
        "金额明细（完整）\n- 设计：10元\n- 开发：20元\n合计：40元\n税费另计",
        "Amount breakdown (complete)\n- A: $10\n- B: $20\nTotal: $40",
        "金额明细（完整）\n- 设计：10元\n- 开发：20元\n合计（含税）：40元",
        "```\n金额明细（完整）\n- 设计：10元\n- 开发：20元\n合计：40元\n```",
        "> 金额明细（完整）\n> - 设计：10元\n> - 开发：20元\n> 合计：40元",
        "金额明细（完整）\n- 设计：10元\n- 开发：“20元”\n合计：40元",
    ],
)
def test_totals_skip_unmarked_incomplete_ambiguous_units_tax_and_examples(text):
    assert check("line_item_total", text) == []


def test_total_skips_document_excerpt():
    text = "金额明细（完整）\n- 设计：10元\n- 开发：20元\n合计：40元"
    assert check("line_item_total", text, complete=False) == []


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("😀计划\n项目：迁移\n开始日期：2026-09-20\n结束日期：2026-09-10", "2026-09-10"),
        ("Project: Migration\nEnd date: 2026-09-10\nStart date: 2026-09-20", "2026-09-10"),
        ("项目：迁移\n开始日期：2026年9月20日\n结束日期：2026年9月10日", "2026年9月10日"),
    ],
)
def test_reversed_explicit_dates_in_same_project(text, fragment):
    assert_hit(check("date_order", text, complete=False), text, fragment)


@pytest.mark.parametrize(
    "text",
    [
        "项目：迁移\n开始日期：2026-09-10\n结束日期：2026-09-20",
        "项目：迁移\n开始日期：2026-09-10\n结束日期：2026-09-10",
        "开始日期：2026-09-20\n结束日期：2026-09-10",
        "项目：甲\n开始日期：2026-09-20\n\n项目：乙\n结束日期：2026-09-10",
        "项目：甲\n开始日期：2026-09-20\n项目：乙\n结束日期：2026-09-10",
        "项目：迁移\n开始日期：2026-09-20\n开始日期：2026-09-01\n结束日期：2026-09-10",
        "项目：迁移\n开始日期：2026-02-30\n结束日期：2026-02-10",
        "项目：迁移\n开始日期：09/20/2026\n结束日期：09/10/2026",
        "项目：迁移\n“开始日期：2026-09-20”\n结束日期：2026-09-10",
        "```\n项目：迁移\n开始日期：2026-09-20\n结束日期：2026-09-10\n```",
        "> 项目：迁移\n> 开始日期：2026-09-20\n> 结束日期：2026-09-10",
    ],
)
def test_dates_skip_unpaired_invalid_ambiguous_and_quoted_values(text):
    assert check("date_order", text) == []


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("😀会议\n待办事项\n- 任务：提交报告；截止：尽快；负责人：张三", "尽快"),
        ("## Action items\n- Task: Send report; Deadline: ASAP; Owner: Alice", "ASAP"),
        ("行动项\n- 任务：提交报告；截止：2026-09-20", "提交报告"),
        ("Tasks\n- [ ] Task: Send report; Deadline: 2026-09-20", "Send report"),
    ],
)
def test_action_list_flags_only_explicit_vague_deadline_or_missing_owner(text, fragment):
    assert_hit(check("action_clarity", text), text, fragment)


@pytest.mark.parametrize(
    "text",
    [
        "请尽快提交报告，我们会积极推进。",
        "- 任务：提交报告；截止：尽快",
        "待办事项\n- 任务：提交报告；截止：2026-09-20；负责人：张三",
        "待办事项\n- 任务：提交报告；截止：尽快（最迟2026-09-20）；负责人：张三",
        "待办事项\n- [x] 任务：提交报告；截止：尽快",
        "待办事项\n负责人：张三\n- 任务：提交报告；截止：2026-09-20",
        "待办事项\n- “任务：提交报告；截止：尽快”",
        "待办事项\n- 任务：`提交报告`；截止：尽快",
        "```\n待办事项\n- 任务：提交报告；截止：尽快\n```",
        "> 待办事项\n> - 任务：提交报告；截止：尽快",
        "待办事项\n\n- 任务：提交报告；截止：尽快",
        "待办事项\n以下是引用的示例：\n- 任务：提交报告；截止：尽快",
        "待办事项\n- 任务：提交报告；截止：尽快；截止：2026-09-20",
    ],
)
def test_action_rule_avoids_prose_examples_completed_tasks_and_contextual_exceptions(text):
    assert check("action_clarity", text) == []


def test_action_rule_does_not_infer_absent_owner_from_excerpt():
    assert check(
        "action_clarity", "待办事项\n- 任务：提交报告；截止：尽快", complete=False
    ) == []


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize(
    ("rule", "text", "fragment"),
    [
        (
            "line_item_total",
            "😀预算\n金额明细\n- 设计：10元\n- 开发：20元\n合计：40元\n\n下一节",
            "40",
        ),
        (
            "date_order",
            "😀计划\n项目：迁移\n开始日期：2026-09-20\n结束日期：2026-09-10\n负责人：张三",
            "2026-09-10",
        ),
        (
            "action_clarity",
            "😀会议\n待办事项\n- [x] 已完成准备\n"
            "- [ ] 任务：提交报告；截止：尽快；负责人：张三",
            "尽快",
        ),
    ],
)
def test_v2_business_hits_preserve_lf_and_crlf_offsets(newline, rule, text, fragment):
    text = text.replace("\n", newline)
    assert_hit(check(rule, text), text, fragment)


@pytest.mark.parametrize(
    "text",
    [
        "项目：迁移\n负责人：张三\n开始日期：2026-09-20\n结束日期：2026-09-10",
        "项目：迁移\n开始日期：2026-09-20\n负责人：张三\n结束日期：2026-09-10",
        "Project: Move\nStart date: 2026-09-20\nEnd date: 2026-09-10\nOwner: Alice",
    ],
)
def test_benign_metadata_keeps_project_date_pair(text):
    assert_hit(check("date_order", text), text, "2026-09-10")


@pytest.mark.parametrize(
    "text",
    [
        "项目：迁移\n开始日期：2026-09-20\n结束日期：2026-09-10\n"
        "负责人：张三\n结束日期：2026-09-30",
        "项目：迁移\n开始日期：2026-09-20\n结束日期：2026-09-10\n"
        "负责人：张三\n结束日期：待定",
        "项目：迁移\n开始日期：2026-09-20\n结束日期：2026-09-10\n备注：以上日期为示例",
        "项目：迁移\n开始日期：2026-09-20\n结束日期：2026-09-10（另一个阶段）\n负责人：张三",
        "项目：甲\n开始日期：2026-09-20\n负责人：张三\n项目：乙\n结束日期：2026-09-10",
        "项目：甲\n开始日期：2026-09-20\n负责人：张三\n\n结束日期：2026-09-10",
        "项目：甲\n开始日期：2026-09-20\n## 阶段乙\n结束日期：2026-09-10",
        "项目：甲\n开始日期：2026-09-20\n负责人：张三；项目：乙\n结束日期：2026-09-10",
    ],
)
def test_metadata_does_not_hide_duplicate_dates_annotations_or_scope_changes(text):
    assert check("date_order", text) == []


@pytest.mark.parametrize("header", ["金额明细", "金额明细（完整）", "Amount breakdown"])
def test_bounded_total_does_not_require_complete_marker(header):
    text = f"{header}\n- 设计：USD 0.10\n- 开发：USD 0.20\nTotal: USD 0.31"
    assert_hit(check("line_item_total", text), text, "0.31")


@pytest.mark.parametrize(
    "rows",
    [
        "- 设计：10元\n- 开发：20元\n合计：40元\n合计：30元",
        "- 设计：10元\n- 开发：20元\n合计：40元\n- 其他：10元",
        "- 设计：10元\n- 开发：20元\n合计：40元\n税费另计",
        "- 设计：10元\n- 开发：20元\n合计：40元\n折扣：10元",
        "- 设计：10元\n- 小计：20元\n合计：40元",
        "- 设计：10元\n- 折扣：20元\n合计：40元",
        "- 设计：10元\n- 开发：20美元\n合计：40元",
        "- 设计：10万元\n- 开发：20元\n合计：40元",
        "- 设计：10元\n- 开发：20元\n合计：30元",
        "- 设计：10元\n- 开发：20元",
        "- 设计：10元\n合计：40元",
    ],
)
def test_unmarked_amount_block_still_rejects_ambiguous_arithmetic(rows):
    assert check("line_item_total", f"金额明细\n{rows}") == []


@pytest.mark.parametrize(
    "text",
    [
        "```\n金额明细\n- 设计：10元\n- 开发：20元\n合计：40元\n```",
        "> 金额明细\n> - 设计：10元\n> - 开发：20元\n> 合计：40元",
        "金额明细\n- 设计：10元\n- 开发：“20元”\n合计：40元",
    ],
)
def test_unmarked_amount_blocks_still_exclude_code_and_quotes(text):
    assert check("line_item_total", text) == []


@pytest.mark.parametrize(
    "completed",
    [
        "- [x] 任务：准备材料；截止：尽快",
        "- [X] Task: Prepare; Deadline: ASAP",
        "- [x] 准备材料",
        "- [x] 核对“准备材料”",
        "- [x] 核对 `report.txt`",
    ],
)
def test_completed_rows_do_not_stop_later_pending_tasks(completed):
    text = f"待办事项\n{completed}\n- 任务：提交报告；截止：2026-09-20"
    assert_hit(check("action_clarity", text), text, "提交报告")


@pytest.mark.parametrize(
    "text",
    [
        "- [x] 准备材料\n- 任务：提交报告；截止：尽快",
        "待办事项\n- [x] 准备材料\n\n- 任务：提交报告；截止：尽快",
        "待办事项\n- [x] 准备材料\n以下是示例：\n- 任务：提交报告；截止：尽快",
        "待办事项\n- [x] 准备材料\n> - 任务：提交报告；截止：尽快",
        "待办事项\n- [x] 准备材料\n- “任务：提交报告；截止：尽快”",
        "待办事项\n- [x] 准备材料\n```\n- 任务：提交报告；截止：尽快\n```",
    ],
)
def test_completed_rows_do_not_create_context_outside_pending_prose_tasks(text):
    assert check("action_clarity", text) == []
