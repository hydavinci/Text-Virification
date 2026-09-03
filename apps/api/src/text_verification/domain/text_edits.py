from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

MAX_REVISION_TEXT_CODEPOINTS = 5_000_000
MAX_REVISION_TEXT_UTF8_BYTES = 25 * 1024 * 1024
MAX_TEXT_DIFF_WORK = 1_000_000
MAX_TEXT_EDIT_OPERATIONS = 10_000


class TextDiffLimitError(ValueError):
    pass


@dataclass
class CheckedTextWorkBudget:
    max_work: int
    max_operations: int
    work: int = 0
    operations: int = 0

    def charge_work(self, units: int) -> None:
        if units < 0:
            raise ValueError("Text work units must be nonnegative.")
        if units > self.max_work - self.work:
            raise TextDiffLimitError(
                "Revision diff exceeds the configured work budget."
            )
        self.work += units

    def charge_operation(self) -> None:
        if self.operations >= self.max_operations:
            raise TextDiffLimitError(
                "Revision diff exceeds the configured edit operation budget."
            )
        self.operations += 1


@dataclass(frozen=True)
class BoundedTextEdit:
    start: int
    end: int
    replacement: str


def validate_revision_text(
    text: str,
    *,
    max_codepoints: int = MAX_REVISION_TEXT_CODEPOINTS,
    max_utf8_bytes: int = MAX_REVISION_TEXT_UTF8_BYTES,
) -> None:
    if len(text) > max_codepoints:
        raise TextDiffLimitError("Revision text exceeds the code-point limit.")
    try:
        encoded_size = len(text.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise TextDiffLimitError("Revision text contains invalid Unicode.") from error
    if encoded_size > max_utf8_bytes:
        raise TextDiffLimitError("Revision text exceeds the UTF-8 byte limit.")


def build_bounded_text_edits(
    original_text: str,
    modified_text: str,
    *,
    max_work: int = MAX_TEXT_DIFF_WORK,
    max_operations: int = MAX_TEXT_EDIT_OPERATIONS,
) -> list[BoundedTextEdit]:
    if original_text == modified_text:
        return []
    if max_operations < 1:
        raise TextDiffLimitError(
            "Revision diff exceeds the configured edit operation budget."
        )

    budget = CheckedTextWorkBudget(max_work, max_operations)
    prefix_length = _common_prefix_length(
        original_text,
        modified_text,
        budget,
    )
    suffix_length = _common_suffix_length(
        original_text,
        modified_text,
        prefix_length,
        budget,
    )
    original_end = len(original_text) - suffix_length
    modified_end = len(modified_text) - suffix_length
    original_middle = original_text[prefix_length:original_end]
    modified_middle = modified_text[prefix_length:modified_end]
    work = (
        len(original_middle) * len(modified_middle)
        if original_middle and modified_middle
        else max(len(original_middle), len(modified_middle))
    )
    budget.charge_work(work)
    budget.charge_work(min(len(original_middle), len(modified_middle)) + 1)

    edits: list[BoundedTextEdit] = []
    matcher = SequenceMatcher(
        a=original_middle,
        b=modified_middle,
        autojunk=False,
    )
    for operation, start, end, new_start, new_end in matcher.get_opcodes():
        if operation == "equal":
            continue
        budget.charge_operation()
        edits.append(
            BoundedTextEdit(
                prefix_length + start,
                prefix_length + end,
                modified_middle[new_start:new_end],
            )
        )
    return edits


def _common_prefix_length(
    left: str,
    right: str,
    budget: CheckedTextWorkBudget,
) -> int:
    limit = min(len(left), len(right))
    index = 0
    while index < limit:
        budget.charge_work(1)
        if left[index] != right[index]:
            break
        index += 1
    return index


def _common_suffix_length(
    left: str,
    right: str,
    prefix_length: int,
    budget: CheckedTextWorkBudget,
) -> int:
    limit = min(len(left), len(right)) - prefix_length
    count = 0
    while count < limit:
        budget.charge_work(1)
        if left[-count - 1] != right[-count - 1]:
            break
        count += 1
    return count
