from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from text_verification.domain.derived_content import (
    DerivedContentValidationError,
    OverlappingReplacementsError,
)
from text_verification.domain.documents import DocumentModel, FileType, TextBlock
from text_verification.domain.issues import (
    DecisionAction,
    Issue,
    IssueDecisionSummary,
    IssueSeverity,
)
from text_verification.exporters import Replacement, ReplacementPlanner


def test_planner_includes_only_accepted_replacements_in_document_order() -> None:
    document = build_document(["第一段", "第二段"])

    plan = ReplacementPlanner().build(
        document,
        [
            build_issue(
                document,
                block_index=1,
                start=0,
                end=2,
                suggestion="系统首选",
                action=DecisionAction.ACCEPTED,
                replacement="末段",
            ),
            build_issue(
                document,
                block_index=0,
                start=0,
                end=2,
                action=DecisionAction.ACCEPTED,
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
    issue = build_issue(
        document,
        block_index=0,
        block_id="missing-block",
        start=0,
        end=2,
        suggestion="替换",
        action=DecisionAction.ACCEPTED,
    )

    with pytest.raises(DerivedContentValidationError) as raised:
        ReplacementPlanner().build(document, [issue])

    assert raised.value.code == "missing_block"
    assert raised.value.issue_ids == (issue.issue_id,)


def test_planner_warns_when_replacement_range_is_out_of_bounds() -> None:
    document = build_document(["正文"])
    issue = build_issue(
        document,
        block_index=0,
        start=0,
        end=10,
        original="正文扩展",
        suggestion="替换",
        action=DecisionAction.ACCEPTED,
    )

    with pytest.raises(DerivedContentValidationError) as raised:
        ReplacementPlanner().build(document, [issue])

    assert raised.value.code == "replacement_out_of_bounds"
    assert raised.value.issue_ids == (issue.issue_id,)


def test_planner_warns_when_original_text_does_not_match_document() -> None:
    document = build_document(["正文"])
    issue = build_issue(
        document,
        block_index=0,
        start=0,
        end=2,
        original="错文",
        suggestion="替换",
        action=DecisionAction.ACCEPTED,
    )

    with pytest.raises(DerivedContentValidationError) as raised:
        ReplacementPlanner().build(document, [issue])

    assert raised.value.code == "original_text_mismatch"
    assert raised.value.issue_ids == (issue.issue_id,)


def test_planner_warns_when_accepted_issue_has_no_final_replacement() -> None:
    document = build_document(["正文"])
    issue = build_issue(
        document,
        block_index=0,
        start=0,
        end=2,
        suggestion=None,
        action=None,
    ).model_copy(
        update={
            "decision": IssueDecisionSummary.model_construct(
                issue_version=document.version,
                revision=0,
                action=DecisionAction.ACCEPTED,
                replacement=None,
                suggestion_id=None,
                updated_at=datetime.now(UTC),
            )
        }
    )

    with pytest.raises(DerivedContentValidationError) as raised:
        ReplacementPlanner().build(document, [issue])

    assert raised.value.code == "missing_replacement_value"
    assert raised.value.issue_ids == (issue.issue_id,)


def test_planner_rejects_overlapping_replacements() -> None:
    document = build_document(["甲乙丙丁"])

    first = build_issue(
        document,
        block_index=0,
        start=0,
        end=3,
        suggestion="A",
        action=DecisionAction.ACCEPTED,
    )
    second = build_issue(
        document,
        block_index=0,
        start=2,
        end=4,
        suggestion="B",
        action=DecisionAction.ACCEPTED,
    )

    with pytest.raises(OverlappingReplacementsError) as raised:
        ReplacementPlanner().build(document, [first, second])

    assert raised.value.issue_ids == tuple(
        sorted((first.issue_id, second.issue_id), key=str)
    )


def test_legacy_planner_skips_invalid_and_overlapping_replacements_with_warnings() -> None:
    document = build_document(["甲乙丙丁"])
    missing_block = build_issue(
        document,
        block_index=0,
        block_id="missing-block",
        start=0,
        end=1,
        suggestion="A",
        action=DecisionAction.ACCEPTED,
    )
    mismatch = build_issue(
        document,
        block_index=0,
        start=1,
        end=2,
        original="错",
        suggestion="B",
        action=DecisionAction.ACCEPTED,
    )
    first_overlap = build_issue(
        document,
        block_index=0,
        start=0,
        end=3,
        suggestion="C",
        action=DecisionAction.ACCEPTED,
    )
    second_overlap = build_issue(
        document,
        block_index=0,
        start=2,
        end=4,
        suggestion="D",
        action=DecisionAction.ACCEPTED,
    )

    plan = ReplacementPlanner().build_legacy(
        document,
        [missing_block, mismatch, first_overlap, second_overlap],
    )

    assert plan.applicable == []
    assert [(warning.code, warning.issue_id) for warning in plan.warnings] == [
        ("missing_block", missing_block.issue_id),
        ("original_text_mismatch", mismatch.issue_id),
        ("overlapping_replacements", first_overlap.issue_id),
        ("overlapping_replacements", second_overlap.issue_id),
    ]


def test_planner_accepts_adjacent_half_open_replacement_ranges() -> None:
    document = build_document(["甲乙丙丁"])

    plan = ReplacementPlanner().build(
        document,
        [
            build_issue(
                document,
                block_index=0,
                start=0,
                end=2,
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

    assert [(item.start, item.end) for item in plan.applicable] == [(0, 2), (2, 4)]
    assert plan.warnings == []


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
        decision_replacement = replacement
        if action == DecisionAction.ACCEPTED and decision_replacement is None:
            decision_replacement = suggestion
        decision = IssueDecisionSummary(
            issue_version=document.version,
            revision=0,
            action=action,
            replacement=decision_replacement,
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
