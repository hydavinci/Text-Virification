from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from text_verification.checkers.models import CHECK_CATEGORY_ORDER, CheckCategory, CheckScenario
from text_verification.domain.issues import DecisionAction, Issue, IssueSeverity

from .docx import ExportError
from .replacements import ExportWarning

HTML: Any = None

DECISION_ORDER = (
    DecisionAction.ACCEPTED.value,
    DecisionAction.CUSTOM.value,
    DecisionAction.IGNORED.value,
    "unreviewed",
)

CATEGORY_LABELS: dict[CheckCategory, str] = {
    CheckCategory.CHARACTER: "字词",
    CheckCategory.VOCABULARY: "词汇",
    CheckCategory.SENTENCE: "句子",
    CheckCategory.FORMAT: "格式",
    CheckCategory.DISCOURSE: "语篇",
    CheckCategory.SECURITY: "安全",
}

SCENARIO_LABELS: dict[CheckScenario, str] = {
    CheckScenario.GENERAL: "通用",
    CheckScenario.ACADEMIC: "学术",
    CheckScenario.BUSINESS: "商务",
    CheckScenario.LEGAL: "法务",
    CheckScenario.NEWS: "新闻",
    CheckScenario.TECHNICAL: "技术",
}

SEVERITY_LABELS: dict[IssueSeverity, str] = {
    IssueSeverity.ERROR: "严重",
    IssueSeverity.WARNING: "警告",
    IssueSeverity.INFO: "提示",
}

DECISION_LABELS: dict[str, str] = {
    DecisionAction.ACCEPTED.value: "接受建议",
    DecisionAction.CUSTOM.value: "自定义替换",
    DecisionAction.IGNORED.value: "忽略",
    "unreviewed": "未处理",
}


@dataclass(frozen=True, slots=True)
class ReportCategoryFailure:
    category: CheckCategory
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ReportSummary:
    total_issues: int
    by_category: Mapping[CheckCategory, int]
    by_severity: Mapping[IssueSeverity, int]
    by_decision: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class ReportModel:
    source_name: str
    generated_at: datetime
    scenario: CheckScenario
    enabled_categories: Sequence[CheckCategory]
    completed_categories: Sequence[CheckCategory]
    failed_categories: Sequence[ReportCategoryFailure]
    summary: ReportSummary
    issues: Sequence[Issue]
    warnings: Sequence[ExportWarning]


class ReportExporter:
    def render_html(self, model: ReportModel, target: Path) -> Path:
        html, _template_dir = self._render(model)
        temp_target = _prepare_temp_target(target)

        try:
            temp_target.write_text(html, encoding="utf-8", newline="\n")
            temp_target.replace(target)
        except Exception as error:
            with suppress(FileNotFoundError):
                temp_target.unlink()
            raise ExportError("report_export_failed", "无法导出问题报告。") from error

        return target

    def render_pdf(self, model: ReportModel, target: Path) -> Path:
        html, template_dir = self._render(model)
        temp_target = _prepare_temp_target(target)

        try:
            _weasyprint_html_class()(string=html, base_url=str(template_dir)).write_pdf(temp_target)
            temp_target.replace(target)
        except Exception as error:
            with suppress(FileNotFoundError):
                temp_target.unlink()
            raise ExportError("report_export_failed", "无法导出问题报告。") from error

        return target

    def _render(self, model: ReportModel) -> tuple[str, Path]:
        template_resource = files("text_verification").joinpath("templates", "issue_report.html")
        if not template_resource.is_file():
            raise ExportError("report_export_failed", "无法导出问题报告。")

        try:
            with as_file(template_resource) as template_path:
                environment = Environment(
                    loader=FileSystemLoader(str(template_path.parent)),
                    autoescape=select_autoescape(
                        enabled_extensions=("html", "xml"),
                        default=True,
                        default_for_string=True,
                    ),
                    undefined=StrictUndefined,
                )
                template = environment.get_template(template_path.name)
                html = template.render(report=self._build_template_context(model))
                return html, template_path.parent
        except ExportError:
            raise
        except Exception as error:
            raise ExportError("report_export_failed", "无法导出问题报告。") from error

    def _build_template_context(self, model: ReportModel) -> dict[str, object]:
        return {
            "source_name": model.source_name,
            "generated_at": _format_datetime(model.generated_at),
            "scenario_label": SCENARIO_LABELS.get(model.scenario, model.scenario.value),
            "enabled_categories": [
                _category_label(category) for category in model.enabled_categories
            ],
            "completed_categories": [
                _category_label(category) for category in model.completed_categories
            ],
            "failed_categories": [
                {
                    "label": _category_label(failure.category),
                    "code": failure.code,
                    "message": failure.message,
                }
                for failure in model.failed_categories
            ],
            "summary": {
                "total_issues": model.summary.total_issues,
                "category_counts": [
                    {
                        "label": _category_label(category),
                        "count": _lookup_count(model.summary.by_category, category),
                    }
                    for category in CHECK_CATEGORY_ORDER
                ],
                "severity_counts": [
                    {
                        "label": SEVERITY_LABELS[severity],
                        "count": _lookup_count(model.summary.by_severity, severity),
                    }
                    for severity in IssueSeverity
                ],
                "decision_counts": [
                    {
                        "label": DECISION_LABELS[decision],
                        "count": int(model.summary.by_decision.get(decision, 0)),
                    }
                    for decision in DECISION_ORDER
                ],
            },
            "issues": [self._build_issue_context(issue) for issue in model.issues],
            "warnings": [
                {
                    "code": warning.code,
                    "message": warning.message,
                    "issue_id": str(warning.issue_id),
                    "block_id": warning.block_id,
                }
                for warning in model.warnings
            ],
        }

    def _build_issue_context(self, issue: Issue) -> dict[str, object]:
        decision = issue.decision
        decision_key = "unreviewed" if decision is None else decision.action.value
        decision_value = None
        if decision is not None and decision.action == DecisionAction.ACCEPTED:
            decision_value = issue.suggestion
        elif decision is not None and decision.action == DecisionAction.CUSTOM:
            decision_value = decision.replacement

        return {
            "issue_id": str(issue.issue_id),
            "category_label": _category_label(issue.layer),
            "severity_label": SEVERITY_LABELS.get(issue.severity, issue.severity.value),
            "page": issue.page,
            "block_id": issue.block_id,
            "range_text": f"{issue.start} - {issue.end}",
            "original": issue.original,
            "suggestion": issue.suggestion,
            "decision_label": DECISION_LABELS[decision_key],
            "decision_value": decision_value,
            "message": issue.message,
            "context": issue.context,
        }


def _prepare_temp_target(target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_target = target.with_name(f"{target.name}.tmp")
    with suppress(FileNotFoundError):
        temp_target.unlink()
    return temp_target


def _category_label(value: CheckCategory | str) -> str:
    category = value
    if not isinstance(category, CheckCategory):
        try:
            category = CheckCategory(category)
        except ValueError:
            return str(value)

    return CATEGORY_LABELS.get(category, category.value)


def _lookup_count(mapping: Mapping[Any, int], key: Any) -> int:
    value = mapping.get(key)
    if value is not None:
        return int(value)

    raw_key = getattr(key, "value", key)
    raw_value = mapping.get(raw_key)
    return int(raw_value or 0)


def _format_datetime(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _weasyprint_html_class() -> Any:
    global HTML
    if HTML is None:
        from weasyprint import HTML as weasyprint_html  # type: ignore[import-untyped]

        HTML = weasyprint_html
    return HTML
