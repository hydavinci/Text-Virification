from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import ParamSpec, Protocol, runtime_checkable
from uuid import UUID, uuid4

from text_verification.domain.documents import DocumentModel, ExportFormat, FileType
from text_verification.domain.issues import Issue
from text_verification.domain.verification import Scenario, VerificationOptions

_ExportParameters = ParamSpec("_ExportParameters")


class VerificationProgressStage(StrEnum):
    PARSING = "parsing"
    OCR = "ocr"
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


@runtime_checkable
class ProgressAwareParser(Protocol):
    def parse_with_progress(
        self,
        source_path: Path,
        *,
        progress_observer: VerificationProgressObserver,
    ) -> DocumentModel: ...


@runtime_checkable
class OcrDeferrableParser(Protocol):
    def parse_without_ocr(self, source_path: Path) -> DocumentModel: ...


@dataclass(frozen=True)
class ResolvedSourcePath:
    root: Path
    relative_path: PurePosixPath

    def __post_init__(self) -> None:
        if not self.root.is_absolute() or ".." in self.root.parts:
            raise ValueError("source root must be absolute and normalized")
        relative_text = self.relative_path.as_posix()
        if (
            self.relative_path.is_absolute()
            or not self.relative_path.parts
            or relative_text in {"", "."}
            or "\x00" in relative_text
            or "\\" in relative_text
            or any(part in {"", ".", ".."} for part in self.relative_path.parts)
            or any(
                len(part) >= 2 and part[1] == ":"
                for part in self.relative_path.parts
            )
        ):
            raise ValueError("source path must be a safe relative path")

    @classmethod
    def from_path(cls, path: Path) -> ResolvedSourcePath:
        if not path.is_absolute() or ".." in path.parts or not path.name:
            raise ValueError("source path must be absolute and normalized")
        return cls(
            root=path.parent,
            relative_path=PurePosixPath(path.name),
        )

    @property
    def path(self) -> Path:
        return self.root.joinpath(*self.relative_path.parts)


class SourcePathResolver(Protocol):
    def resolve(
        self,
        document: DocumentModel,
        *,
        source_path: Path | None = None,
    ) -> Path: ...


class AnchoredSourcePathResolver(Protocol):
    def resolve_anchored(self, document: DocumentModel) -> ResolvedSourcePath: ...


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
