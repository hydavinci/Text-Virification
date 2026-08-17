from __future__ import annotations

import re
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pypdf import PdfReader

from text_verification.checkers.models import CHECK_CATEGORY_ORDER, CheckCategory, CheckScenario
from text_verification.domain.issues import (
    DecisionAction,
    Issue,
    IssueDecisionSummary,
    IssueSeverity,
)
from text_verification.exporters.replacements import ExportWarning

DECISION_ORDER = ("accepted", "custom", "ignored", "unreviewed")


def test_html_and_pdf_reports_share_title_counts_and_issues(tmp_path: Path) -> None:
    report_module, ReportExporter, *_rest = _report_symbols()
    issues = [
        build_issue(
            index=1,
            category=CheckCategory.CHARACTER,
            original="示例文本",
            suggestion="专业文本",
            action=DecisionAction.ACCEPTED,
        ),
        build_issue(
            index=2,
            category=CheckCategory.SECURITY,
            original="风险词",
            suggestion="中性词",
            action=DecisionAction.CUSTOM,
            replacement="稳妥词",
        ),
    ]
    model = build_report_model(report_module, source_name="sample.docx", issues=issues)

    html_path = ReportExporter().render_html(model, tmp_path / "report.html")
    pdf_path = ReportExporter().render_pdf(model, tmp_path / "report.pdf")

    html = html_path.read_text(encoding="utf-8")
    pdf_text = _normalize_text(_read_pdf_text(pdf_path))

    assert "sample.docx" in html
    assert "发现问题：2" in html
    assert "示例文本" in html
    assert "sample.docx" in pdf_text
    assert "发现问题：2" in pdf_text
    assert "示例文本" in pdf_text


def test_report_html_escapes_source_issue_and_warning_values(tmp_path: Path) -> None:
    report_module, ReportExporter, *_rest = _report_symbols()
    issues = [
        build_issue(
            index=1,
            category=CheckCategory.VOCABULARY,
            original="<b>原文</b>",
            suggestion="<i>建议</i>",
            action=DecisionAction.CUSTOM,
            replacement="<u>替换</u>",
            message="<strong>提示</strong>",
            context="<section>上下文</section>",
        )
    ]
    model = build_report_model(
        report_module,
        source_name="<span>sample</span>.docx",
        issues=issues,
        warning_message="<mark>警告</mark>",
    )

    html = ReportExporter().render_html(
        model,
        tmp_path / "escaped.html",
    ).read_text(encoding="utf-8")

    assert "<span>sample</span>.docx" not in html
    assert "&lt;span&gt;sample&lt;/span&gt;.docx" in html
    assert "<b>原文</b>" not in html
    assert "&lt;b&gt;原文&lt;/b&gt;" in html
    assert "<section>上下文</section>" not in html
    assert "&lt;section&gt;上下文&lt;/section&gt;" in html
    assert "<mark>警告</mark>" not in html
    assert "&lt;mark&gt;警告&lt;/mark&gt;" in html


def test_render_pdf_surfaces_failure_and_removes_partial_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_module, ReportExporter, *_symbols, ExportError = _report_symbols()
    target = tmp_path / "report.pdf"

    class FailingHTML:
        def __init__(self, *, string: str, base_url: str) -> None:
            self.string = string
            self.base_url = base_url

        def write_pdf(self, destination: Path) -> None:
            destination.write_bytes(b"partial-pdf")
            raise RuntimeError("boom")

    monkeypatch.setattr(report_module, "HTML", FailingHTML)

    with pytest.raises(ExportError) as raised:
        ReportExporter().render_pdf(
            build_report_model(
                report_module,
                source_name="sample.docx",
                issues=[build_issue(index=1)],
            ),
            target,
        )

    assert raised.value.code == "report_export_failed"
    assert raised.value.public_message == "无法导出问题报告。"
    assert not target.exists()
    assert not (tmp_path / "report.pdf.tmp").exists()


def build_report_model(
    report_module: Any,
    *,
    source_name: str,
    issues: list[Issue],
    warning_message: str = "导出时跳过 1 项。<safe>",
) -> Any:
    by_category = {category: 0 for category in CHECK_CATEGORY_ORDER}
    by_severity = {severity: 0 for severity in IssueSeverity}
    by_decision = {decision: 0 for decision in DECISION_ORDER}

    for issue in issues:
        by_category[CheckCategory(issue.layer)] += 1
        by_severity[issue.severity] += 1
        decision = issue.decision.action.value if issue.decision is not None else "unreviewed"
        by_decision[decision] += 1

    summary = report_module.ReportSummary(
        total_issues=len(issues),
        by_category=by_category,
        by_severity=by_severity,
        by_decision=by_decision,
    )
    first_issue = issues[0]

    return report_module.ReportModel(
        source_name=source_name,
        generated_at=datetime(2026, 8, 17, 9, 30, tzinfo=UTC),
        scenario=CheckScenario.GENERAL,
        enabled_categories=(CheckCategory.CHARACTER, CheckCategory.SECURITY),
        completed_categories=(CheckCategory.CHARACTER,),
        failed_categories=(
            report_module.ReportCategoryFailure(
                category=CheckCategory.SECURITY,
                code="checker_failed",
                message="安全分类检查失败。",
            ),
        ),
        summary=summary,
        issues=tuple(issues),
        warnings=(
            ExportWarning(
                code="missing_replacement_value",
                message=warning_message,
                issue_id=first_issue.issue_id,
                block_id=first_issue.block_id,
            ),
        ),
    )


def build_issue(
    *,
    index: int,
    category: CheckCategory = CheckCategory.CHARACTER,
    original: str = "示例文本",
    suggestion: str | None = "专业文本",
    action: DecisionAction | None = DecisionAction.ACCEPTED,
    replacement: str | None = None,
    message: str = "命中规则。",
    context: str = "原文上下文示例文本",
) -> Issue:
    issue_id = UUID(f"00000000-0000-0000-0000-{index:012d}")
    if action is None:
        decision = None
    else:
        decision = IssueDecisionSummary(
            issue_version=1,
            action=action,
            replacement=replacement if action == DecisionAction.CUSTOM else None,
            updated_at=datetime(2026, 8, 17, 9, 31, tzinfo=UTC),
        )

    return Issue(
        issue_id=issue_id,
        document_id=UUID("00000000-0000-0000-0000-000000000100"),
        document_version=1,
        block_id=f"p-{index:06d}",
        page=index,
        start=0,
        end=max(len(original), 1),
        original=original,
        suggestion=suggestion,
        alternatives=[] if suggestion is None else [suggestion],
        type="literal",
        severity=IssueSeverity.WARNING,
        layer=category.value,
        message=message,
        rule_id=f"{category.value}-{index:03d}",
        source="test",
        source_version="1",
        confidence=1.0,
        auto_fixable=suggestion is not None,
        context=context,
        decision=decision,
    )


def _report_symbols():
    try:
        package = import_module("text_verification.exporters")
        report_module = import_module("text_verification.exporters.report")
    except ModuleNotFoundError as error:
        pytest.fail(f"Report exporter is not implemented yet: {error}")

    try:
        return (
            report_module,
            package.ReportExporter,
            package.ReportModel,
            package.ReportSummary,
            package.ReportCategoryFailure,
            package.ExportError,
        )
    except AttributeError as error:
        pytest.fail(f"Report exporter is not implemented yet: {error}")


def _read_pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    return "".join(page.extract_text() or "" for page in reader.pages)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", value)
