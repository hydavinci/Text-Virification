from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

from text_verification.domain.dictionaries import TerritoryStandardRule
from text_verification.domain.documents import DocumentModel, TextBlock
from text_verification.domain.issues import Issue, IssueSeverity
from text_verification.domain.ports import CheckContext

CONTEXT_RADIUS = 20


@dataclass(frozen=True)
class _DictionaryMatch:
    start: int
    end: int
    original: str
    suggestion: str | None
    message: str
    rule_id: str
    source_version: str
    issue_type: str


class DictionaryChecker:
    name = "shared-dictionaries"
    version = "1"
    supported_languages = {"zh-CN"}
    supported_scenarios: set[str] = set()

    def check(self, document: DocumentModel, context: CheckContext) -> list[Issue]:
        issues: list[Issue] = []
        dictionaries = context.shared_dictionaries
        for block in document.blocks:
            matches = [
                *self._literal_matches(
                    block.text,
                    dictionaries.advertising.extreme_words,
                    namespace="advertising-extreme",
                    message="检测到广告合规极限用语，请核对并改写。",
                    source_version=dictionaries.advertising.version,
                ),
                *self._literal_matches(
                    block.text,
                    dictionaries.compliance.politics,
                    namespace="compliance-politics",
                    message="检测到政治类合规词，请联系合规人员复核。",
                    source_version=dictionaries.compliance.version,
                ),
                *self._literal_matches(
                    block.text,
                    dictionaries.compliance.ethnic_religion,
                    namespace="compliance-ethnic-religion",
                    message="检测到民族宗教类合规词，请联系合规人员复核。",
                    source_version=dictionaries.compliance.version,
                ),
                *self._territory_matches(
                    block.text,
                    dictionaries.compliance.territory_standard,
                    source_version=dictionaries.compliance.version,
                ),
            ]
            for match in sorted(
                matches,
                key=lambda item: (item.start, item.end, item.rule_id),
            ):
                issues.append(
                    self._build_issue(document.document_id, document.version, block, match)
                )
        return issues

    def _literal_matches(
        self,
        text: str,
        terms: Iterable[str],
        *,
        namespace: str,
        message: str,
        source_version: str,
    ) -> Iterator[_DictionaryMatch]:
        for term in terms:
            search_from = 0
            while True:
                start = text.find(term, search_from)
                if start == -1:
                    break
                end = start + len(term)
                yield _DictionaryMatch(
                    start=start,
                    end=end,
                    original=term,
                    suggestion=None,
                    message=message,
                    rule_id=self._rule_id(namespace, term),
                    source_version=source_version,
                    issue_type="dictionary_literal",
                )
                search_from = start + 1

    def _territory_matches(
        self,
        text: str,
        rules: Iterable[TerritoryStandardRule],
        *,
        source_version: str,
    ) -> Iterator[_DictionaryMatch]:
        for rule in rules:
            for matched in re.finditer(rule.bad, text):
                yield _DictionaryMatch(
                    start=matched.start(),
                    end=matched.end(),
                    original=matched.group(0),
                    suggestion=rule.good,
                    message=rule.note,
                    rule_id=self._rule_id("compliance-territory", rule.bad),
                    source_version=source_version,
                    issue_type="dictionary_regex",
                )

    def _build_issue(
        self,
        document_id: UUID,
        document_version: int,
        block: TextBlock,
        match: _DictionaryMatch,
    ) -> Issue:
        return Issue(
            issue_id=uuid5(
                NAMESPACE_URL,
                (
                    f"{document_id}:v{document_version}:{match.rule_id}:{block.block_id}:"
                    f"{match.start}:{match.end}"
                ),
            ),
            document_id=document_id,
            block_id=block.block_id,
            page=block.page,
            start=match.start,
            end=match.end,
            original=match.original,
            suggestion=match.suggestion,
            alternatives=[] if match.suggestion is None else [match.suggestion],
            type=match.issue_type,
            severity=IssueSeverity.WARNING,
            layer="security",
            message=match.message,
            rule_id=match.rule_id,
            source="shared_dictionary",
            source_version=match.source_version,
            confidence=1.0,
            auto_fixable=match.suggestion is not None,
            context=block.text[
                max(0, match.start - CONTEXT_RADIUS) : min(
                    len(block.text),
                    match.end + CONTEXT_RADIUS,
                )
            ],
        )

    def _rule_id(self, namespace: str, value: str) -> str:
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
        return f"dictionary-{namespace}-{digest}"
