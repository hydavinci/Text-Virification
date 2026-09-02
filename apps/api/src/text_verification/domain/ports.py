from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import ParamSpec, Protocol
from uuid import UUID, uuid4

from text_verification.domain.documents import DocumentModel, ExportFormat, FileType
from text_verification.domain.issues import Issue
from text_verification.domain.verification import Scenario, VerificationOptions

_ExportParameters = ParamSpec("_ExportParameters")


class VerificationProgressStage(StrEnum):
    PARSING = "parsing"
    CHECKING_FORMAT = "checking_format"
    CHECKING_SENSITIVE = "checking_sensitive"
    CHECKING_CHINESE = "checking_chinese"
    CHECKING_ENGLISH = "checking_english"


class VerificationProgressObserver(Protocol):
    def __call__(self, stage: VerificationProgressStage) -> None: ...


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


@dataclass(frozen=True)
class CheckResult:
    issues: tuple[Issue, ...]
    dictionary_versions: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "issues", tuple(self.issues))
        object.__setattr__(
            self,
            "dictionary_versions",
            MappingProxyType(dict(self.dictionary_versions)),
        )

    def issue_list(self) -> list[Issue]:
        return list(self.issues)


class Parser(Protocol):
    supported_type: FileType

    def parse(self, source_path: Path) -> DocumentModel: ...


class Checker(Protocol):
    name: str
    version: str
    supported_languages: set[str]

    def check(
        self,
        document: DocumentModel,
        context: CheckContext,
        *,
        progress_observer: VerificationProgressObserver | None = None,
    ) -> CheckResult: ...


class Exporter(Protocol[_ExportParameters]):
    @property
    def file_type(self) -> FileType | ExportFormat: ...

    def export(
        self,
        document: DocumentModel,
        *args: _ExportParameters.args,
        **kwargs: _ExportParameters.kwargs,
    ) -> Path: ...
