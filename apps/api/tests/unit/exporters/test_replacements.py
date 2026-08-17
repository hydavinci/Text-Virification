from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from text_verification.domain.documents import DocumentModel, FileType, TextBlock
from text_verification.domain.issues import (
    DecisionAction,
    Issue,
    IssueDecisionSummary,
    IssueSeverity,
)
from text_verification.exporters import Replacement, ReplacementPlanner


def test_planner_includes_only_accepted_and_custom_replacements_in_document_order() -> None:
    document = build_document(["第一段", "第二段"])

    plan = ReplacementPlanner().build(
        document,
        [
            build_issue(
                document,
                block_index=1,
                start=0,
                end=2,
                suggestion="末段",
                action=DecisionAction.ACCEPTED,
            ),
            build_issue(
                document,
                block_index=0,
                start=0,
                end=2,
                action=DecisionAction.CUSTOM,
                replacement="首段",
            ),
            build_issue(
                document,
                block_index=0,
                start=2,
                end=3,
                suggestion="忽",
                action=DecisionAction.IGNORED,
            ),
            build_issue(
                document,
                block_index=1,
                start=2,
                end=3,
                suggestion="略",
                action=None,
            ),
        ],
    )

    assert plan.applicable == [
        Replacement(
            block_id="p-000001",
            start=0,
            end=2,
            original="第一",
            value="首段",
            issue_id=UUID("00000000-0000-0000-0000-000000000001"),
        ),
        Replacement(
            block_id="p-000002",
            start=0,
            end=2,
            original="第二",
            value="末段",
            issue_id=UUID("00000000-0000-0000-0000-000000000002"),
        ),
    ]
    assert plan.warnings == []


def test_planner_warns_when_referenced_block_is_missing() -> None:
    document = build_document(["正文"])

    plan = ReplacementPlanner().build(
        document,
        [
            build_issue(
                document,
                block_index=0,
                block_id="missing-block",
                start=0,
                end=2,
                suggestion="替换",
                action=DecisionAction.ACCEPTED,
            )
        ],
    )

    assert plan.applicable == []
    assert [warning.code for warning in plan.warnings] == ["missing_block"]


def test_planner_warns_when_replacement_range_is_out_of_bounds() -> None:
    document = build_document(["正文"])

    plan = ReplacementPlanner().build(
        document,
        [
            build_issue(
                document,
                block_index=0,
                start=0,
                end=10,
                original="正文扩展",
                suggestion="替换",
                action=DecisionAction.ACCEPTED,
            )
        ],
    )

    assert plan.applicable == []
    assert [warning.code for warning in plan.warnings] == ["replacement_out_of_bounds"]


def test_planner_warns_when_original_text_does_not_match_document() -> None:
    document = build_document(["正文"])

    plan = ReplacementPlanner().build(
        document,
        [
            build_issue(
                document,
                block_index=0,
                start=0,
                end=2,
                original="错文",
                suggestion="替换",
                action=DecisionAction.ACCEPTED,
            )
        ],
    )

    assert plan.applicable == []
    assert [warning.code for warning in plan.warnings] == ["original_text_mismatch"]


def test_planner_warns_when_accepted_issue_has_no_suggestion() -> None:
    document = build_document(["正文"])

    plan = ReplacementPlanner().build(
        document,
        [
            build_issue(
                document,
                block_index=0,
                start=0,
                end=2,
                suggestion=None,
                action=DecisionAction.ACCEPTED,
            )
        ],
    )

    assert plan.applicable == []
    assert [warning.code for warning in plan.warnings] == ["missing_replacement_value"]


def test_planner_rejects_overlapping_replacements() -> None:
    document = build_document(["甲乙丙丁"])

    plan = ReplacementPlanner().build(
        document,
        [
            build_issue(
                document,
                block_index=0,
                start=0,
                end=3,
                suggestion="A",
                action=DecisionAction.ACCEPTED,
            ),
            build_issue(
                document,
                block_index=0,
                start=2,
                end=4,
                suggestion="B",
                action=DecisionAction.ACCEPTED,
            ),
        ],
    )

    assert plan.applicable == []
    assert [warning.code for warning in plan.warnings] == [
        "overlapping_replacements",
        "overlapping_replacements",
    ]


def build_document(block_texts: list[str]) -> DocumentModel:
    blocks = [
        TextBlock(
            block_id=f"p-{index + 1:06d}",
            kind="paragraph",
            text=text,
            page=None,
            paragraph_index=index,
            parent_id=None,
            style={"style_name": "Normal"},
            source_locator={"paragraph_index": index},
        )
        for index, text in enumerate(block_texts)
    ]
    return DocumentModel(
        document_id=UUID("00000000-0000-0000-0000-000000000001"),
        file_type=FileType.TXT,
        source_name="analysis.txt",
        version=1,
        blocks=blocks,
        metadata={"encoding": "utf-8"},
    )


def build_issue(
    document: DocumentModel,
    *,
    block_index: int,
    start: int,
    end: int,
    suggestion: str | None = None,
    action: DecisionAction | None,
    replacement: str | None = None,
    original: str | None = None,
    block_id: str | None = None,
) -> Issue:
    block = document.blocks[block_index]
    issue_number = block_index + start + 1
    issue_id = UUID(f"00000000-0000-0000-0000-{issue_number:012d}")
    if action is None:
        decision = None
    else:
        decision = IssueDecisionSummary(
            issue_version=document.version,
            action=action,
            replacement=replacement if action == DecisionAction.CUSTOM else None,
            updated_at=datetime.now(UTC),
        )

    return Issue(
        issue_id=issue_id,
        document_id=document.document_id,
        document_version=document.version,
        block_id=block_id or block.block_id,
        page=None,
        start=start,
        end=end,
        original=original if original is not None else block.text[start:end],
        suggestion=suggestion,
        alternatives=[] if suggestion is None else [suggestion],
        type="literal",
        severity=IssueSeverity.WARNING,
        layer="security",
        message="命中规则。",
        rule_id="security-001",
        source="test",
        source_version="1",
        confidence=1.0,
        auto_fixable=suggestion is not None,
        context=block.text,
        decision=decision,
    )
