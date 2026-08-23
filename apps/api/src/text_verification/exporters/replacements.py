from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from text_verification.domain.derived_content import (
    DerivedDocument,
    Replacement,
    derive_document,
)
from text_verification.domain.documents import DocumentModel
from text_verification.domain.exports import ExportWarning
from text_verification.domain.issues import DecisionAction, Issue

_LEGACY_VERSION_ID = UUID(int=0)


@dataclass(frozen=True, slots=True)
class ReplacementPlan:
    applicable: list[Replacement]
    warnings: list[ExportWarning]


class ReplacementPlanner:
    def build(
        self,
        document: DocumentModel,
        issues_with_decisions: Iterable[Issue],
        *,
        version_id: UUID = _LEGACY_VERSION_ID,
    ) -> ReplacementPlan:
        derived = derive_document(
            version_id,
            document,
            tuple(issues_with_decisions),
        )
        return self.from_derived(derived)

    def from_derived(self, derived: DerivedDocument) -> ReplacementPlan:
        return ReplacementPlan(
            applicable=list(derived.replacements),
            warnings=[],
        )

    def build_legacy(
        self,
        document: DocumentModel,
        issues_with_decisions: Iterable[Issue],
    ) -> ReplacementPlan:
        block_by_id = {block.block_id: block for block in document.blocks}
        block_order = {
            block.block_id: index for index, block in enumerate(document.blocks)
        }
        candidates: list[Replacement] = []
        warnings: list[ExportWarning] = []

        for issue in issues_with_decisions:
            decision = issue.decision
            if decision is None or decision.action != DecisionAction.ACCEPTED:
                continue

            block = block_by_id.get(issue.block_id)
            if block is None:
                warnings.append(
                    _build_warning(
                        issue,
                        code="missing_block",
                        message="问题引用的文本块不存在，已跳过；请重新分析文档后再导出。",
                    )
                )
                continue

            if issue.start > len(block.text) or issue.end > len(block.text):
                warnings.append(
                    _build_warning(
                        issue,
                        code="replacement_out_of_bounds",
                        message="问题的替换范围超出文本块边界，已跳过；请重新分析文档后再导出。",
                    )
                )
                continue

            if block.text[issue.start : issue.end] != issue.original:
                warnings.append(
                    _build_warning(
                        issue,
                        code="original_text_mismatch",
                        message="问题的原文与当前文档内容不一致，已跳过；请重新分析文档后再导出。",
                    )
                )
                continue

            if decision.replacement is None:
                warnings.append(
                    _build_warning(
                        issue,
                        code="missing_replacement_value",
                        message="问题缺少可应用的替换内容，已跳过；请补充建议或自定义替换后再导出。",
                    )
                )
                continue

            candidates.append(
                Replacement(
                    block_id=issue.block_id,
                    start=issue.start,
                    end=issue.end,
                    original=issue.original,
                    value=decision.replacement,
                    issue_id=issue.issue_id,
                )
            )

        applicable, overlap_warnings = _filter_overlapping_replacements(
            candidates,
            block_order=block_order,
        )
        return ReplacementPlan(applicable=applicable, warnings=[*warnings, *overlap_warnings])


def _filter_overlapping_replacements(
    replacements: list[Replacement],
    *,
    block_order: dict[str, int],
) -> tuple[list[Replacement], list[ExportWarning]]:
    ordered = sorted(
        replacements,
        key=lambda replacement: (
            block_order[replacement.block_id],
            replacement.start,
            replacement.end,
            str(replacement.issue_id),
        ),
    )
    applicable: list[Replacement] = []
    warnings: list[ExportWarning] = []
    current_cluster: list[Replacement] = []
    current_block_id: str | None = None
    current_cluster_end = -1

    def flush_cluster() -> None:
        if not current_cluster:
            return
        if len(current_cluster) == 1:
            applicable.extend(current_cluster)
            return
        for replacement in current_cluster:
            warnings.append(
                ExportWarning(
                    code="overlapping_replacements",
                    message="问题与其他修改范围重叠，相关修改均已跳过；请逐项调整后再导出。",
                    issue_id=replacement.issue_id,
                    block_id=replacement.block_id,
                )
            )

    for replacement in ordered:
        starts_new_cluster = (
            not current_cluster
            or replacement.block_id != current_block_id
            or replacement.start >= current_cluster_end
        )
        if starts_new_cluster:
            flush_cluster()
            current_cluster = [replacement]
            current_block_id = replacement.block_id
            current_cluster_end = replacement.end
            continue

        current_cluster.append(replacement)
        current_cluster_end = max(current_cluster_end, replacement.end)

    flush_cluster()
    return applicable, warnings


def _build_warning(issue: Issue, *, code: str, message: str) -> ExportWarning:
    return ExportWarning(
        code=code,
        message=message,
        issue_id=issue.issue_id,
        block_id=issue.block_id,
    )
