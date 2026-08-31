from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from text_verification.domain.documents import DocumentModel, FileType
from text_verification.domain.issues import Issue
from text_verification.domain.verification import Scenario, VerificationOptions


@dataclass(frozen=True)
class CheckContext:
    industry_dictionary_ids: tuple[str, ...] = ()
    personal_dictionary: tuple[dict[str, str], ...] = ()
    scenario: Scenario = Scenario.GENERAL
    enable_security: bool = True
    enable_sensitive: bool = True
    enable_ad_extreme: bool = False
    custom_glossary: tuple[dict[str, str], ...] = ()
    banned_words: tuple[str, ...] = ()
    verification_run_id: UUID = field(default_factory=uuid4)

    @classmethod
    def from_options(cls, options: VerificationOptions) -> CheckContext:
        glossary = tuple(
            {"original": term.original, "standard": term.standard}
            for term in options.custom_glossary
            if term.original != term.standard
        )
        banned_words = tuple(
            dict.fromkeys(word.strip() for word in options.banned_words if word.strip())
        )
        return cls(
            personal_dictionary=glossary,
            scenario=options.scenario,
            enable_security=options.enable_security,
            enable_sensitive=options.enable_sensitive,
            enable_ad_extreme=options.enable_ad_extreme,
            custom_glossary=glossary,
            banned_words=banned_words,
        )


class Parser(Protocol):
    supported_type: FileType

    def parse(self, source_path: Path) -> DocumentModel: ...


class Checker(Protocol):
    name: str
    version: str
    supported_languages: set[str]

    def check(self, document: DocumentModel, context: CheckContext) -> list[Issue]: ...


class Exporter(Protocol):
    file_type: FileType

    def export(
        self,
        document: DocumentModel,
        issues: list[Issue],
        target: Path,
        *,
        source_path: Path | None = None,
        track_changes: bool = False,
        modified_text: str | None = None,
    ) -> Path: ...
