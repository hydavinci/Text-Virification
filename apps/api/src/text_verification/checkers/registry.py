from __future__ import annotations

from collections.abc import Iterable

from text_verification.domain.documents import DocumentModel
from text_verification.domain.issues import Issue
from text_verification.domain.ports import CheckContext, Checker
from text_verification.registry_errors import DuplicateCapabilityError, MissingCapabilityError

_LAYER_ORDER = {
    "character": 0,
    "vocabulary": 1,
    "sentence": 2,
    "format": 3,
    "discourse": 4,
    "security": 5,
}


class CheckerRegistry:
    def __init__(self, checkers: Iterable[Checker] = ()) -> None:
        self._checkers: list[Checker] = []
        self._names: set[str] = set()
        for checker in checkers:
            self.register(checker)

    def register(self, checker: Checker) -> None:
        if checker.name in self._names:
            raise DuplicateCapabilityError("checker", checker.name)
        self._checkers.append(checker)
        self._names.add(checker.name)

    def run(self, document: DocumentModel, context: CheckContext) -> list[Issue]:
        if not self._checkers:
            raise MissingCapabilityError("checker", "run")

        issues_with_order: list[tuple[int, int, int, Issue]] = []
        for checker_index, checker in enumerate(self._checkers):
            for issue_index, issue in enumerate(checker.check(document, context)):
                issues_with_order.append(
                    (
                        _LAYER_ORDER.get(issue.layer, len(_LAYER_ORDER)),
                        checker_index,
                        issue_index,
                        issue,
                    )
                )
        issues_with_order.sort(key=lambda item: item[:3])
        return [issue for _, _, _, issue in issues_with_order]
