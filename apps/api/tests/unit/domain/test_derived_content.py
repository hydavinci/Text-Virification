from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from text_verification.domain.derived_content import (
    DerivedContentValidationError,
    DiffKind,
    OverlappingReplacementsError,
    derive_document,
    myers_diff,
)
from text_verification.domain.documents import DocumentModel, FileType, TextBlock
from text_verification.domain.issues import (
    DecisionAction,
    Issue,
    IssueDecisionSummary,
    IssueSeverity,
)

VERSION_ID = UUID("00000000-0000-0000-0000-000000000100")


def test_derived_document_applies_replacements_from_right_to_left() -> None:
    derived = derive_document(
        VERSION_ID,
        document("甲乙丙丁"),
        [
            accepted_issue(0, 1, "甲", "A"),
            accepted_issue(2, 4, "丙丁", "CD"),
        ],
    )

    assert derived.document.blocks[0].text == "A乙CD"


def test_derived_document_uses_stored_final_replacement_not_suggestion() -> None:
    issue = accepted_issue(0, 2, "原文", "最终文本").model_copy(
        update={"suggestion": "系统首选"}
    )

    derived = derive_document(VERSION_ID, document("原文正文"), [issue])

    assert derived.document.blocks[0].text == "最终文本正文"


def test_derived_document_allows_empty_final_replacement() -> None:
    issue = accepted_issue(0, 2, "删除", "临时").model_copy(
        update={
            "decision": IssueDecisionSummary.model_construct(
                issue_version=1,
                revision=1,
                action=DecisionAction.ACCEPTED,
                replacement="",
                suggestion_id=None,
                updated_at=datetime(2026, 8, 22, tzinfo=UTC),
            )
        }
    )

    derived = derive_document(VERSION_ID, document("删除正文"), [issue])

    assert derived.document.blocks[0].text == "正文"


def test_derived_document_preserves_unchanged_blocks() -> None:
    source = document("第一段", "第二段")

    derived = derive_document(
        VERSION_ID,
        source,
        [accepted_issue(0, 2, "第一", "首段", block_index=0)],
    )

    assert [block.text for block in derived.document.blocks] == ["首段段", "第二段"]
    assert derived.document.blocks[1] == source.blocks[1]
    assert source.blocks[0].text == "第一段"


def test_derived_document_handles_astral_unicode_offsets() -> None:
    derived = derive_document(
        VERSION_ID,
        document("A😀B"),
        [accepted_issue(1, 2, "😀", "🚀")],
    )

    assert derived.document.blocks[0].text == "A🚀B"


def test_decision_snapshot_hash_is_stable_for_issue_order_and_suggestions() -> None:
    first = accepted_issue(0, 1, "甲", "A")
    second = ignored_issue(2, 3, "丙")

    ordered = derive_document(VERSION_ID, document("甲乙丙"), [first, second])
    reordered = derive_document(
        VERSION_ID,
        document("甲乙丙"),
        [
            second.model_copy(update={"suggestion": "不应进入快照"}),
            first.model_copy(update={"suggestion": "另一个系统首选"}),
        ],
    )

    assert ordered.decision_snapshot_sha256 == reordered.decision_snapshot_sha256
    assert len(ordered.decision_snapshot_sha256) == 64


def test_decision_snapshot_hash_changes_with_version_or_final_replacement() -> None:
    source = document("原文")
    initial = derive_document(
        VERSION_ID,
        source,
        [accepted_issue(0, 2, "原文", "替换")],
    )
    other_version = derive_document(
        UUID("00000000-0000-0000-0000-000000000101"),
        source,
        [accepted_issue(0, 2, "原文", "替换")],
    )
    other_replacement = derive_document(
        VERSION_ID,
        source,
        [accepted_issue(0, 2, "原文", "修订")],
    )

    assert initial.decision_snapshot_sha256 != other_version.decision_snapshot_sha256
    assert initial.decision_snapshot_sha256 != other_replacement.decision_snapshot_sha256


def test_derived_document_rejects_mismatched_original_text() -> None:
    issue = accepted_issue(0, 2, "错文", "替换")

    with pytest.raises(DerivedContentValidationError) as raised:
        derive_document(VERSION_ID, document("正文"), [issue])

    assert raised.value.code == "original_text_mismatch"
    assert raised.value.issue_ids == (issue.issue_id,)


def test_derived_document_rejects_out_of_bounds_range() -> None:
    issue = accepted_issue(0, 3, "正文扩", "替换")

    with pytest.raises(DerivedContentValidationError) as raised:
        derive_document(VERSION_ID, document("正文"), [issue])

    assert raised.value.code == "replacement_out_of_bounds"
    assert raised.value.issue_ids == (issue.issue_id,)


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (-1, 1),
        (2, 1),
    ],
    ids=["negative-start", "end-before-start"],
)
def test_derived_document_rejects_invalid_half_open_ranges(
    start: int,
    end: int,
) -> None:
    issue = accepted_issue(0, 1, "正", "替").model_copy(
        update={"start": start, "end": end, "original": ""}
    )

    with pytest.raises(DerivedContentValidationError) as raised:
        derive_document(VERSION_ID, document("正文"), [issue])

    assert raised.value.code == "replacement_out_of_bounds"
    assert raised.value.issue_ids == (issue.issue_id,)


def test_derived_document_rejects_every_issue_in_overlapping_clusters() -> None:
    first = accepted_issue(0, 3, "甲乙丙", "A")
    second = accepted_issue(2, 4, "丙丁", "B")
    third = accepted_issue(1, 2, "乙", "C", block_index=1)
    fourth = accepted_issue(1, 3, "乙丙", "D", block_index=1)

    with pytest.raises(OverlappingReplacementsError) as raised:
        derive_document(
            VERSION_ID,
            document("甲乙丙丁", "甲乙丙丁"),
            [fourth, second, first, third],
        )

    assert raised.value.issue_ids == tuple(
        sorted(
            (first.issue_id, second.issue_id, third.issue_id, fourth.issue_id),
            key=str,
        )
    )


def test_modified_text_and_diff_reconstruct_same_value() -> None:
    segments = myers_diff("文字错误", "文本正确")

    assert "".join(s.text for s in segments if s.kind != "delete") == "文本正确"


def test_myers_diff_is_character_level_and_coalesces_adjacent_segments() -> None:
    segments = myers_diff("甲乙丙丁", "甲AB丁")

    assert [(segment.kind, segment.text) for segment in segments] == [
        (DiffKind.EQUAL, "甲"),
        (DiffKind.DELETE, "乙丙"),
        (DiffKind.INSERT, "AB"),
        (DiffKind.EQUAL, "丁"),
    ]


def test_myers_diff_handles_astral_unicode() -> None:
    segments = myers_diff("A😀B", "A🚀B")

    assert [(segment.kind, segment.text) for segment in segments] == [
        (DiffKind.EQUAL, "A"),
        (DiffKind.DELETE, "😀"),
        (DiffKind.INSERT, "🚀"),
        (DiffKind.EQUAL, "B"),
    ]


@pytest.mark.parametrize(
    ("original", "modified", "expected"),
    [
        ("", "新增", [(DiffKind.INSERT, "新增")]),
        ("删除", "", [(DiffKind.DELETE, "删除")]),
        ("", "", []),
    ],
)
def test_myers_diff_handles_empty_values(
    original: str,
    modified: str,
    expected: list[tuple[DiffKind, str]],
) -> None:
    segments = myers_diff(original, modified)

    assert [(segment.kind, segment.text) for segment in segments] == expected


def document(*texts: str) -> DocumentModel:
    return DocumentModel(
        document_id=UUID("00000000-0000-0000-0000-000000000001"),
        file_type=FileType.TXT,
        source_name="analysis.txt",
        version=1,
        blocks=[
            TextBlock(
                block_id=f"p-{index + 1:06d}",
                kind="paragraph",
                text=text,
                page=None,
                paragraph_index=index,
                parent_id=None,
                style={},
                source_locator={"paragraph_index": index},
            )
            for index, text in enumerate(texts)
        ],
        metadata={"encoding": "utf-8"},
    )


def accepted_issue(
    start: int,
    end: int,
    original: str,
    replacement: str,
    *,
    block_index: int = 0,
) -> Issue:
    return issue_with_decision(
        start,
        end,
        original,
        block_index=block_index,
        action=DecisionAction.ACCEPTED,
        replacement=replacement,
    )


def ignored_issue(
    start: int,
    end: int,
    original: str,
    *,
    block_index: int = 0,
) -> Issue:
    return issue_with_decision(
        start,
        end,
        original,
        block_index=block_index,
        action=DecisionAction.IGNORED,
        replacement=None,
    )


def issue_with_decision(
    start: int,
    end: int,
    original: str,
    *,
    block_index: int,
    action: DecisionAction,
    replacement: str | None,
) -> Issue:
    issue_number = block_index * 100 + start + end
    return Issue(
        issue_id=UUID(f"00000000-0000-0000-0000-{issue_number:012d}"),
        document_id=UUID("00000000-0000-0000-0000-000000000001"),
        document_version=1,
        block_id=f"p-{block_index + 1:06d}",
        page=None,
        start=start,
        end=end,
        original=original,
        suggestion="系统建议",
        alternatives=["系统建议"],
        type="literal",
        severity=IssueSeverity.WARNING,
        layer="character",
        message="命中规则。",
        rule_id="character-001",
        source="test",
        source_version="1",
        confidence=1.0,
        auto_fixable=True,
        context=original,
        decision=IssueDecisionSummary(
            issue_version=1,
            revision=1,
            action=action,
            replacement=replacement,
            suggestion_id=None,
            updated_at=datetime(2026, 8, 22, tzinfo=UTC),
        ),
    )
