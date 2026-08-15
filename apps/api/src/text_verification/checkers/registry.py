from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import cast

from text_verification.checkers.models import (
    CHECK_CATEGORY_ORDER,
    CheckCategory,
    CheckerFailure,
    CheckOptions,
    CheckRunResult,
    RuleSet,
)
from text_verification.checkers.rule_checker import RuleChecker
from text_verification.domain.documents import DocumentModel
from text_verification.domain.issues import Issue
from text_verification.domain.ports import CheckContext, Checker

LOGGER = logging.getLogger(__name__)

FAILURE_MESSAGES: dict[CheckCategory, str] = {
    CheckCategory.CHARACTER: "字词检查暂时不可用。",
    CheckCategory.VOCABULARY: "词汇检查暂时不可用。",
    CheckCategory.SENTENCE: "句子检查暂时不可用。",
    CheckCategory.FORMAT: "格式检查暂时不可用。",
    CheckCategory.DISCOURSE: "篇章检查暂时不可用。",
    CheckCategory.SECURITY: "安全检查暂时不可用。",
}


class CheckerRegistry:
    def __init__(
        self,
        checkers_by_category: Mapping[CheckCategory, Checker | Iterable[Checker]],
    ) -> None:
        self._checkers = {
            category: self._normalize_checkers(checkers)
            for category, checkers in checkers_by_category.items()
        }

    @classmethod
    def from_rule_set(
        cls,
        rule_set: RuleSet,
        *,
        source: str = "local_rules",
    ) -> CheckerRegistry:
        grouped: defaultdict[CheckCategory, list[Checker]] = defaultdict(list)
        for rule in rule_set.rules:
            grouped[rule.category].append(
                RuleChecker(rule, source=source, source_version=rule_set.version)
            )
        return cls(grouped)

    def run(
        self,
        document: DocumentModel,
        context: CheckContext,
        options: CheckOptions,
    ) -> CheckRunResult:
        issues: list[Issue] = []
        completed_categories: set[CheckCategory] = set()
        failures: dict[CheckCategory, CheckerFailure] = {}

        for category in CHECK_CATEGORY_ORDER:
            if category not in options.enabled_categories:
                continue

            try:
                for checker in self._checkers.get(category, ()):
                    if not self._supports_scenario(checker, options):
                        continue
                    issues.extend(checker.check(document, context))
            except Exception as error:  # pragma: no cover - behavior asserted via public result
                LOGGER.error(
                    "Checker category %s failed with %s",
                    category.value,
                    error.__class__.__name__,
                )
                failures[category] = CheckerFailure(
                    code="checker_failed",
                    message=FAILURE_MESSAGES[category],
                )
                continue

            completed_categories.add(category)

        return CheckRunResult(
            issues=issues,
            completed_categories=completed_categories,
            failures=failures,
        )

    def _supports_scenario(self, checker: Checker, options: CheckOptions) -> bool:
        supported_scenarios = getattr(checker, "supported_scenarios", None)
        if supported_scenarios is None:
            return True
        if not supported_scenarios:
            return True
        return options.scenario.value in supported_scenarios

    def _normalize_checkers(
        self,
        checkers: Checker | Iterable[Checker],
    ) -> tuple[Checker, ...]:
        if hasattr(checkers, "check"):
            return (cast(Checker, checkers),)
        return tuple(checkers)
