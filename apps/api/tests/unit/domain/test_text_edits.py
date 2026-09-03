import pytest

from text_verification.domain.text_edits import (
    TextDiffLimitError,
    build_bounded_text_edits,
    validate_revision_text,
)


def test_revision_text_limits_are_inclusive_for_code_points_and_utf8_bytes() -> None:
    validate_revision_text(
        "😀a",
        max_codepoints=2,
        max_utf8_bytes=5,
    )

    with pytest.raises(TextDiffLimitError, match="code-point"):
        validate_revision_text(
            "😀ab",
            max_codepoints=2,
            max_utf8_bytes=6,
        )
    with pytest.raises(TextDiffLimitError, match="UTF-8"):
        validate_revision_text(
            "😀ab",
            max_codepoints=3,
            max_utf8_bytes=5,
        )


def test_bounded_diff_accepts_the_exact_work_boundary() -> None:
    edits = build_bounded_text_edits(
        "a" * 10,
        "b" * 10,
        max_work=100,
        max_operations=2,
    )

    assert [(edit.start, edit.end, edit.replacement) for edit in edits] == [
        (0, 10, "b" * 10)
    ]


def test_bounded_diff_rejects_work_above_the_boundary_before_matching() -> None:
    with pytest.raises(TextDiffLimitError, match="work budget"):
        build_bounded_text_edits(
            "a" * 10,
            "b" * 11,
            max_work=100,
            max_operations=2,
        )


def test_bounded_diff_rejects_adversarial_repeated_text_without_timing_assertions() -> None:
    repeated = "ab" * 600

    with pytest.raises(TextDiffLimitError, match="work budget"):
        build_bounded_text_edits(
            repeated + "x",
            "x" + repeated,
            max_work=1_000_000,
            max_operations=10_000,
        )


def test_bounded_diff_rejects_too_many_edit_operations() -> None:
    with pytest.raises(TextDiffLimitError, match="operation budget"):
        build_bounded_text_edits(
            "abc",
            "axc",
            max_work=100,
            max_operations=0,
        )
