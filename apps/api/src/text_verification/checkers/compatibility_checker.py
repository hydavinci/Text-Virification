from __future__ import annotations

from typing import Protocol, cast

from text_verification.compatibility.adapters import legacy_issues_to_domain
from text_verification.compatibility.analyzer import Issue as LegacyIssue
from text_verification.compatibility.analyzer import TextAnalyzer
from text_verification.domain.documents import DocumentModel
from text_verification.domain.issues import Issue
from text_verification.domain.ports import CheckContext
from text_verification.infrastructure.dictionary_loader import DictionaryLoader


class LegacyAnalyzer(Protocol):
    dictionary_versions: dict[str, str]

    def analyze(
        self,
        text: str,
        *,
        scenario: str = "general",
        custom_glossary: list[dict[str, str]] | None = None,
        banned_words: list[str] | None = None,
        enable_security: bool = True,
        enable_sensitive: bool = True,
        enable_ad_extreme: bool = False,
    ) -> list[LegacyIssue]: ...


class CompatibilityChecker:
    name = "compatibility"
    version = "1"
    supported_languages = {"zh", "en"}

    def __init__(
        self,
        analyzer: LegacyAnalyzer | None = None,
        *,
        dictionary_loader: DictionaryLoader | None = None,
    ) -> None:
        self._analyzer = analyzer or cast(
            LegacyAnalyzer,
            TextAnalyzer(dictionary_loader=dictionary_loader or DictionaryLoader()),
        )
        self._dictionary_versions: dict[str, str] = {}

    @property
    def dictionary_versions(self) -> dict[str, str]:
        return dict(self._dictionary_versions)

    def check(self, document: DocumentModel, context: CheckContext) -> list[Issue]:
        issues = self._analyzer.analyze(
            document.text,
            scenario=context.scenario.value,
            custom_glossary=list(context.custom_glossary),
            banned_words=list(context.banned_words),
            enable_security=context.enable_security,
            enable_sensitive=context.enable_sensitive,
            enable_ad_extreme=context.enable_ad_extreme,
        )
        self._dictionary_versions = self._analyzer.dictionary_versions
        return list(legacy_issues_to_domain(issues, document, context.verification_run_id))
