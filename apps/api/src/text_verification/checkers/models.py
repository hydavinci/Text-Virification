from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from text_verification.domain.issues import Issue, IssueSeverity


class CheckCategory(StrEnum):
    CHARACTER = "character"
    VOCABULARY = "vocabulary"
    SENTENCE = "sentence"
    FORMAT = "format"
    DISCOURSE = "discourse"
    SECURITY = "security"


CHECK_CATEGORY_ORDER: tuple[CheckCategory, ...] = (
    CheckCategory.CHARACTER,
    CheckCategory.VOCABULARY,
    CheckCategory.SENTENCE,
    CheckCategory.FORMAT,
    CheckCategory.DISCOURSE,
    CheckCategory.SECURITY,
)


class CheckScenario(StrEnum):
    GENERAL = "general"
    BUSINESS = "business"
    NEWS = "news"
    LEGAL = "legal"
    EDUCATION = "education"
    MEDICAL = "medical"


@dataclass(frozen=True)
class LiteralRule:
    id: str
    category: CheckCategory
    severity: IssueSeverity
    pattern: str
    suggestion: str | None
    message: str
    scenarios: frozenset[CheckScenario]
    auto_fixable: bool


@dataclass(frozen=True)
class RuleSet:
    version: str
    scenarios_version: str
    allowed_scenarios: frozenset[CheckScenario]
    rules: tuple[LiteralRule, ...]


@dataclass(frozen=True)
class CheckOptions:
    scenario: CheckScenario
    enabled_categories: frozenset[CheckCategory]

    def __init__(
        self,
        scenario: CheckScenario | str = CheckScenario.GENERAL,
        enabled_categories: Iterable[CheckCategory | str] = CHECK_CATEGORY_ORDER,
    ) -> None:
        parsed_categories = frozenset(
            _parse_check_category(category) for category in enabled_categories
        )
        if not parsed_categories:
            raise ValueError("enabled_categories must not be empty")

        object.__setattr__(self, "scenario", _parse_check_scenario(scenario))
        object.__setattr__(self, "enabled_categories", parsed_categories)


@dataclass(frozen=True)
class CheckerFailure:
    code: str
    message: str


@dataclass(frozen=True)
class CheckRunResult:
    issues: list[Issue]
    completed_categories: set[CheckCategory]
    failures: dict[CheckCategory, CheckerFailure]


def _parse_check_category(value: CheckCategory | str) -> CheckCategory:
    if isinstance(value, CheckCategory):
        return value
    return CheckCategory(value)


def _parse_check_scenario(value: CheckScenario | str) -> CheckScenario:
    if isinstance(value, CheckScenario):
        return value
    return CheckScenario(value)
