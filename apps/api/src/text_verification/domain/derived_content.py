from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from text_verification.domain.documents import DocumentModel
from text_verification.domain.issues import DecisionAction, Issue


class DiffKind(StrEnum):
    EQUAL = "equal"
    INSERT = "insert"
    DELETE = "delete"


class DiffSegment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: DiffKind
    text: str


@dataclass(frozen=True, slots=True)
class Replacement:
    block_id: str
    start: int
    end: int
    original: str
    value: str
    issue_id: UUID


@dataclass(frozen=True, slots=True)
class DerivedDocument:
    document: DocumentModel
    replacements: tuple[Replacement, ...]
    decision_snapshot_sha256: str


class DerivedContentValidationError(ValueError):
    def __init__(self, code: str, issue_ids: Sequence[UUID]) -> None:
        self.code = code
        self.issue_ids = tuple(sorted(set(issue_ids), key=str))
        super().__init__(f"{code}: {', '.join(str(value) for value in self.issue_ids)}")


class OverlappingReplacementsError(DerivedContentValidationError):
    def __init__(self, issue_ids: Sequence[UUID]) -> None:
        super().__init__("overlapping_replacements", issue_ids)


def derive_document(
    version_id: UUID,
    document: DocumentModel,
    issues: Sequence[Issue],
) -> DerivedDocument:
    replacements = _validated_replacements(document, issues)
    replacements_by_block: dict[str, list[Replacement]] = defaultdict(list)
    for replacement in replacements:
        replacements_by_block[replacement.block_id].append(replacement)

    derived_blocks = []
    for block in document.blocks:
        text = block.text
        for replacement in reversed(replacements_by_block.get(block.block_id, [])):
            text = text[: replacement.start] + replacement.value + text[replacement.end :]
        derived_blocks.append(block.model_copy(update={"text": text}, deep=True))

    derived_document = document.model_copy(
        update={"blocks": derived_blocks},
        deep=True,
    )
    return DerivedDocument(
        document=derived_document,
        replacements=tuple(replacements),
        decision_snapshot_sha256=_decision_snapshot_sha256(version_id, issues),
    )


def myers_diff(original: str, modified: str) -> Sequence[DiffSegment]:
    if original == modified:
        return [] if not original else [DiffSegment(kind=DiffKind.EQUAL, text=original)]

    operations = _myers_operations(original, modified)
    segments: list[DiffSegment] = []
    for kind, text in operations:
        if segments and segments[-1].kind == kind:
            previous = segments[-1]
            segments[-1] = DiffSegment(kind=kind, text=previous.text + text)
        else:
            segments.append(DiffSegment(kind=kind, text=text))
    return segments


def _validated_replacements(
    document: DocumentModel,
    issues: Sequence[Issue],
) -> list[Replacement]:
    block_by_id = {block.block_id: block for block in document.blocks}
    block_order = {block.block_id: index for index, block in enumerate(document.blocks)}
    replacements: list[Replacement] = []

    for issue in issues:
        decision = issue.decision
        if decision is None or decision.action != DecisionAction.ACCEPTED:
            continue
        block = block_by_id.get(issue.block_id)
        if block is None:
            raise DerivedContentValidationError("missing_block", [issue.issue_id])
        if (
            issue.start < 0
            or issue.end < issue.start
            or issue.start > len(block.text)
            or issue.end > len(block.text)
        ):
            raise DerivedContentValidationError(
                "replacement_out_of_bounds",
                [issue.issue_id],
            )
        if block.text[issue.start : issue.end] != issue.original:
            raise DerivedContentValidationError(
                "original_text_mismatch",
                [issue.issue_id],
            )
        if decision.replacement is None:
            raise DerivedContentValidationError(
                "missing_replacement_value",
                [issue.issue_id],
            )
        replacements.append(
            Replacement(
                block_id=issue.block_id,
                start=issue.start,
                end=issue.end,
                original=issue.original,
                value=decision.replacement,
                issue_id=issue.issue_id,
            )
        )

    replacements.sort(
        key=lambda replacement: (
            block_order[replacement.block_id],
            replacement.start,
            replacement.end,
            str(replacement.issue_id),
        )
    )
    overlapping_issue_ids = _overlapping_issue_ids(replacements)
    if overlapping_issue_ids:
        raise OverlappingReplacementsError(sorted(overlapping_issue_ids))
    return replacements


def _overlapping_issue_ids(replacements: Sequence[Replacement]) -> set[UUID]:
    overlapping: set[UUID] = set()
    cluster: list[Replacement] = []
    cluster_block_id: str | None = None
    cluster_end = -1

    for replacement in replacements:
        if (
            not cluster
            or replacement.block_id != cluster_block_id
            or replacement.start >= cluster_end
        ):
            cluster = [replacement]
            cluster_block_id = replacement.block_id
            cluster_end = replacement.end
            continue
        overlapping.update(item.issue_id for item in cluster)
        overlapping.add(replacement.issue_id)
        cluster.append(replacement)
        cluster_end = max(cluster_end, replacement.end)

    return overlapping


def _decision_snapshot_sha256(version_id: UUID, issues: Sequence[Issue]) -> str:
    decisions = [
        {
            "issue_id": str(issue.issue_id),
            **issue.decision.model_dump(mode="json"),
        }
        for issue in issues
        if issue.decision is not None
    ]
    decisions.sort(key=lambda decision: str(decision["issue_id"]))
    canonical_json = json.dumps(
        {
            "version_id": str(version_id),
            "decisions": decisions,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical_json.encode("utf-8")).hexdigest()


def _myers_operations(
    original: str,
    modified: str,
) -> list[tuple[DiffKind, str]]:
    original_length = len(original)
    modified_length = len(modified)
    furthest: dict[int, int] = {1: 0}
    trace: list[dict[int, int]] = []

    for distance in range(original_length + modified_length + 1):
        trace.append(furthest.copy())
        for diagonal in range(-distance, distance + 1, 2):
            if diagonal == -distance or (
                diagonal != distance
                and furthest.get(diagonal - 1, -1)
                < furthest.get(diagonal + 1, -1)
            ):
                x = furthest.get(diagonal + 1, 0)
            else:
                x = furthest.get(diagonal - 1, 0) + 1
            y = x - diagonal
            while (
                x < original_length
                and y < modified_length
                and original[x] == modified[y]
            ):
                x += 1
                y += 1
            furthest[diagonal] = x
            if x >= original_length and y >= modified_length:
                return _backtrack_myers(trace, original, modified, distance)

    raise RuntimeError("Myers diff did not terminate")


def _backtrack_myers(
    trace: Sequence[dict[int, int]],
    original: str,
    modified: str,
    distance: int,
) -> list[tuple[DiffKind, str]]:
    x = len(original)
    y = len(modified)
    reversed_operations: list[tuple[DiffKind, str]] = []

    for current_distance in range(distance, 0, -1):
        furthest = trace[current_distance]
        diagonal = x - y
        if diagonal == -current_distance or (
            diagonal != current_distance
            and furthest.get(diagonal - 1, -1)
            < furthest.get(diagonal + 1, -1)
        ):
            previous_diagonal = diagonal + 1
            edit_kind = DiffKind.INSERT
        else:
            previous_diagonal = diagonal - 1
            edit_kind = DiffKind.DELETE

        previous_x = furthest[previous_diagonal]
        previous_y = previous_x - previous_diagonal
        while x > previous_x and y > previous_y:
            x -= 1
            y -= 1
            reversed_operations.append((DiffKind.EQUAL, original[x]))

        if edit_kind == DiffKind.INSERT:
            y -= 1
            reversed_operations.append((DiffKind.INSERT, modified[y]))
        else:
            x -= 1
            reversed_operations.append((DiffKind.DELETE, original[x]))

    while x > 0 and y > 0:
        x -= 1
        y -= 1
        reversed_operations.append((DiffKind.EQUAL, original[x]))
    while x > 0:
        x -= 1
        reversed_operations.append((DiffKind.DELETE, original[x]))
    while y > 0:
        y -= 1
        reversed_operations.append((DiffKind.INSERT, modified[y]))

    reversed_operations.reverse()
    return reversed_operations
