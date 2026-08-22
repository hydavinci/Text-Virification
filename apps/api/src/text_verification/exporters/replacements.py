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
from text_verification.domain.issues import Issue

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
