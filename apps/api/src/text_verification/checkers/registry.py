from __future__ import annotations

from collections.abc import Iterable

from text_verification.domain.documents import DocumentModel
from text_verification.domain.issues import Issue
from text_verification.domain.ports import (
    CheckContext,
    Checker,
    CheckResult,
    VerificationProgressObserver,
)
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

    def run(
        self,
        document: DocumentModel,
        context: CheckContext,
        *,
        progress_observer: VerificationProgressObserver | None = None,
    ) -> CheckResult:
        if not self._checkers:
            raise MissingCapabilityError("checker", "run")

        issues_with_order: list[tuple[int, int, int, Issue]] = []
        dictionary_versions: dict[str, str] = {}
        for checker_index, checker in enumerate(self._checkers):
            if progress_observer is None:
                result = checker.check(document, context)
            else:
                result = checker.check(
                    document,
                    context,
                    progress_observer=progress_observer,
                )
            dictionary_versions.update(result.dictionary_versions)
            for issue_index, issue in enumerate(result.issues):
                issues_with_order.append(
                    (
                        _LAYER_ORDER.get(issue.layer, len(_LAYER_ORDER)),
                        checker_index,
                        issue_index,
                        issue,
                    )
                )
        issues_with_order.sort(key=lambda item: item[:3])
        return CheckResult(
            issues=tuple(issue for _, _, _, issue in issues_with_order),
            dictionary_versions=dictionary_versions,
        )
