from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

from text_verification.checkers.models import LiteralRule
from text_verification.domain.documents import DocumentModel, TextBlock
from text_verification.domain.issues import Issue
from text_verification.domain.ports import CheckContext

CONTEXT_RADIUS = 20


class RuleChecker:
    supported_languages = {"zh-CN"}

    def __init__(
        self,
        rule: LiteralRule,
        *,
        source: str = "local_rules",
        source_version: str = "1",
    ) -> None:
        self._rule = rule
        self.name = f"literal:{rule.id}"
        self.version = source_version
        self.supported_scenarios = {scenario.value for scenario in rule.scenarios}
        self._source = source
        self._source_version = source_version

    def check(self, document: DocumentModel, context: CheckContext) -> list[Issue]:
        del context
        issues: list[Issue] = []
        for block in document.blocks:
            issues.extend(
                self._check_block(document.document_id, document.version, block)
            )
        return issues

    def _check_block(
        self,
        document_id: UUID,
        document_version: int,
        block: TextBlock,
    ) -> list[Issue]:
        issues: list[Issue] = []
        search_from = 0
        while True:
            start = block.text.find(self._rule.pattern, search_from)
            if start == -1:
                return issues

            end = start + len(self._rule.pattern)
            issues.append(self._build_issue(document_id, document_version, block, start, end))
            search_from = start + 1

    def _build_issue(
        self,
        document_id: UUID,
        document_version: int,
        block: TextBlock,
        start: int,
        end: int,
    ) -> Issue:
        suggestion = self._rule.suggestion
        return Issue(
            issue_id=uuid5(
                NAMESPACE_URL,
                (
                    f"{document_id}:v{document_version}:"
                    f"{self._rule.id}:{block.block_id}:{start}:{end}"
                ),
            ),
            document_id=document_id,
            block_id=block.block_id,
            page=block.page,
            start=start,
            end=end,
            original=self._rule.pattern,
            suggestion=suggestion,
            alternatives=[] if suggestion is None else [suggestion],
            type="literal",
            severity=self._rule.severity,
            layer=self._rule.category.value,
            message=self._rule.message,
            rule_id=self._rule.id,
            source=self._source,
            source_version=self._source_version,
            confidence=1.0,
            auto_fixable=self._rule.auto_fixable,
            context=self._context_window(block.text, start, end),
        )

    def _context_window(self, text: str, start: int, end: int) -> str:
        return text[max(0, start - CONTEXT_RADIUS) : min(len(text), end + CONTEXT_RADIUS)]
