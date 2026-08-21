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

DECISION_ORDER = ("accepted", "ignored", "unreviewed")


def test_html_and_pdf_reports_share_title_counts_issues_failures_and_warnings(
    tmp_path: Path,
) -> None:
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
            action=DecisionAction.ACCEPTED,
            replacement="稳妥词",
        ),
    ]
    model = build_report_model(report_module, source_name="sample.docx", issues=issues)

    html_path = ReportExporter().render_html(model, tmp_path / "report.html")
    pdf_path = ReportExporter().render_pdf(model, tmp_path / "report.pdf")

    html = html_path.read_text(encoding="utf-8")
    normalized_html = _normalize_text(html)
    pdf_text = _normalize_text(_read_pdf_text(pdf_path))

    assert "sample.docx" in html
    assert "发现问题：2" in html
    assert "示例文本" in html
    assert "checker_failed" in normalized_html
    assert "安全分类检查失败。" in normalized_html
    assert "missing_replacement_value" in normalized_html
    assert "导出时跳过1项。" in normalized_html
    assert "sample.docx" in pdf_text
    assert "发现问题：2" in pdf_text
    assert "示例文本" in pdf_text
    assert "checker_failed" in pdf_text
    assert "安全分类检查失败。" in pdf_text
    assert "missing_replacement_value" in pdf_text
    assert "导出时跳过1项。" in pdf_text


def test_html_and_pdf_reports_render_unknown_issue_layer_as_raw_text(tmp_path: Path) -> None:
    report_module, ReportExporter, *_rest = _report_symbols()
    issue = build_issue(index=1, layer="future-layer", original="未来术语")
    model = build_report_model(report_module, source_name="future.docx", issues=[issue])

    html_path = ReportExporter().render_html(model, tmp_path / "future.html")
    pdf_path = ReportExporter().render_pdf(model, tmp_path / "future.pdf")

    html = html_path.read_text(encoding="utf-8")
    pdf_text = _normalize_text(_read_pdf_text(pdf_path))

    assert "future-layer" in html
    assert "future-layer" in pdf_text


def test_report_html_escapes_source_issue_and_warning_values(tmp_path: Path) -> None:
    report_module, ReportExporter, *_rest = _report_symbols()
    issues = [
        build_issue(
            index=1,
            category=CheckCategory.VOCABULARY,
            original="<b>原文</b>",
            suggestion="<i>建议</i>",
            action=DecisionAction.ACCEPTED,
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


@pytest.mark.parametrize("failure_point", ("write_text", "replace"))
def test_render_html_surfaces_failure_and_removes_partial_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    report_module, ReportExporter, *_symbols, ExportError = _report_symbols()
    target = tmp_path / "report.html"
    temp_target = target.with_name(f"{target.name}.tmp")
    original_write_text = Path.write_text
    original_replace = Path.replace

    def failing_write_text(
        self: Path,
        data: str,
        *args: object,
        **kwargs: object,
    ) -> int:
        if failure_point == "write_text" and self == temp_target:
            original_write_text(self, "partial-html", encoding="utf-8")
            raise OSError("boom")
        return original_write_text(self, data, *args, **kwargs)

    def failing_replace(self: Path, destination: str | Path) -> Path:
        if failure_point == "replace" and self == temp_target and Path(destination) == target:
            raise OSError("boom")
        return original_replace(self, destination)

    monkeypatch.setattr(Path, "write_text", failing_write_text)
    monkeypatch.setattr(Path, "replace", failing_replace)

    with pytest.raises(ExportError) as raised:
        ReportExporter().render_html(
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
    assert not temp_target.exists()


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
    warning_message: str = "导出时跳过 1 项。",
) -> Any:
    by_category = {category: 0 for category in CHECK_CATEGORY_ORDER}
    by_severity = {severity: 0 for severity in IssueSeverity}
    by_decision = {decision: 0 for decision in DECISION_ORDER}

    for issue in issues:
        try:
            by_category[CheckCategory(issue.layer)] += 1
        except ValueError:
            pass
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
    layer: str | None = None,
    original: str = "示例文本",
    suggestion: str | None = "专业文本",
    action: DecisionAction | None = DecisionAction.ACCEPTED,
    replacement: str | None = None,
    message: str = "命中规则。",
    context: str = "原文上下文示例文本",
) -> Issue:
    issue_id = UUID(f"00000000-0000-0000-0000-{index:012d}")
    layer_value = category.value if layer is None else layer
    if action is None:
        decision = None
    else:
        decision_replacement = replacement
        if action == DecisionAction.ACCEPTED and decision_replacement is None:
            decision_replacement = suggestion
        decision = IssueDecisionSummary(
            issue_version=1,
            revision=0,
            action=action,
            replacement=decision_replacement,
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
        layer=layer_value,
        message=message,
        rule_id=f"{layer_value}-{index:03d}",
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
