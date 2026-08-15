from __future__ import annotations

import json
from pathlib import Path

from text_verification.checkers.models import (
    CheckCategory,
    CheckScenario,
    LiteralRule,
    RuleSet,
)
from text_verification.domain.issues import IssueSeverity


class RuleConfigurationError(ValueError):
    """Raised when a rule configuration file is invalid."""


class RuleLoader:
    def __init__(self, rule_path: Path, scenario_path: Path) -> None:
        self._rule_path = rule_path
        self._scenario_path = scenario_path

    def load(self) -> RuleSet:
        scenarios_version, allowed_scenarios = self._load_scenarios()
        payload = self._read_json(self._rule_path)
        version = self._require_non_empty_string(payload, "version", self._rule_path)
        raw_rules = payload.get("rules")
        if not isinstance(raw_rules, list) or not raw_rules:
            raise RuleConfigurationError(f"{self._rule_path}: rules must be a non-empty list")

        seen_ids: set[str] = set()
        rules: list[LiteralRule] = []
        for index, raw_rule in enumerate(raw_rules, start=1):
            if not isinstance(raw_rule, dict):
                raise RuleConfigurationError(
                    f"{self._rule_path}: rules[{index}] must be an object"
                )

            rule_id = self._require_non_empty_string(
                raw_rule,
                "id",
                self._rule_path,
                context=f"rules[{index}]",
            )
            if rule_id in seen_ids:
                raise RuleConfigurationError(
                    f"{self._rule_path}: duplicate rule id {rule_id!r}"
                )
            seen_ids.add(rule_id)

            category = self._parse_category(
                self._require_non_empty_string(
                    raw_rule,
                    "category",
                    self._rule_path,
                    context=rule_id,
                ),
                rule_id,
            )
            severity = self._parse_severity(
                self._require_non_empty_string(
                    raw_rule,
                    "severity",
                    self._rule_path,
                    context=rule_id,
                ),
                rule_id,
            )
            pattern = self._require_non_empty_string(
                raw_rule,
                "pattern",
                self._rule_path,
                context=rule_id,
            )
            suggestion = self._optional_non_empty_string(
                raw_rule,
                "suggestion",
                self._rule_path,
                context=rule_id,
            )
            message = self._require_non_empty_string(
                raw_rule,
                "message",
                self._rule_path,
                context=rule_id,
            )
            scenarios = self._parse_rule_scenarios(
                raw_rule.get("scenarios"),
                rule_id,
                allowed_scenarios,
            )
            auto_fixable = raw_rule.get("auto_fixable")
            if not isinstance(auto_fixable, bool):
                raise RuleConfigurationError(
                    f"{self._rule_path}: {rule_id} auto_fixable must be a boolean"
                )

            rules.append(
                LiteralRule(
                    id=rule_id,
                    category=category,
                    severity=severity,
                    pattern=pattern,
                    suggestion=suggestion,
                    message=message,
                    scenarios=scenarios,
                    auto_fixable=auto_fixable,
                )
            )

        return RuleSet(
            version=version,
            scenarios_version=scenarios_version,
            allowed_scenarios=allowed_scenarios,
            rules=tuple(rules),
        )

    def _load_scenarios(self) -> tuple[str, frozenset[CheckScenario]]:
        payload = self._read_json(self._scenario_path)
        version = self._require_non_empty_string(payload, "version", self._scenario_path)
        raw_scenarios = payload.get("scenarios")
        if not isinstance(raw_scenarios, list) or not raw_scenarios:
            raise RuleConfigurationError(
                f"{self._scenario_path}: scenarios must be a non-empty list"
            )

        parsed: set[CheckScenario] = set()
        for index, raw_scenario in enumerate(raw_scenarios, start=1):
            if not isinstance(raw_scenario, dict):
                raise RuleConfigurationError(
                    f"{self._scenario_path}: scenarios[{index}] must be an object"
                )

            scenario_id = self._require_non_empty_string(
                raw_scenario,
                "id",
                self._scenario_path,
                context=f"scenarios[{index}]",
            )
            scenario = self._parse_scenario(scenario_id)
            if scenario in parsed:
                raise RuleConfigurationError(
                    f"{self._scenario_path}: duplicate scenario id {scenario.value!r}"
                )
            parsed.add(scenario)
            self._require_non_empty_string(
                raw_scenario,
                "label",
                self._scenario_path,
                context=scenario.value,
            )

        expected = frozenset(CheckScenario)
        actual = frozenset(parsed)
        if actual != expected:
            missing = sorted(
                scenario.value for scenario in expected if scenario not in actual
            )
            raise RuleConfigurationError(
                f"{self._scenario_path}: missing scenarios {missing!r}"
            )

        return version, actual

    def _read_json(self, path: Path) -> dict[str, object]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except OSError as error:
            raise RuleConfigurationError(f"{path}: {error.strerror}") from error
        except json.JSONDecodeError as error:
            raise RuleConfigurationError(
                f"{path}: invalid JSON at line {error.lineno} column {error.colno}"
            ) from error

        if not isinstance(payload, dict):
            raise RuleConfigurationError(f"{path}: root must be an object")
        return payload

    def _parse_category(self, value: str, rule_id: str) -> CheckCategory:
        try:
            return CheckCategory(value)
        except ValueError as error:
            raise RuleConfigurationError(
                f"{self._rule_path}: {rule_id} category {value!r} is unknown"
            ) from error

    def _parse_severity(self, value: str, rule_id: str) -> IssueSeverity:
        try:
            return IssueSeverity(value)
        except ValueError as error:
            raise RuleConfigurationError(
                f"{self._rule_path}: {rule_id} severity {value!r} is invalid"
            ) from error

    def _parse_scenario(self, value: str) -> CheckScenario:
        try:
            return CheckScenario(value)
        except ValueError as error:
            raise RuleConfigurationError(
                f"{self._scenario_path}: scenario {value!r} is unknown"
            ) from error

    def _parse_rule_scenarios(
        self,
        raw_value: object,
        rule_id: str,
        allowed_scenarios: frozenset[CheckScenario],
    ) -> frozenset[CheckScenario]:
        if not isinstance(raw_value, list) or not raw_value:
            raise RuleConfigurationError(
                f"{self._rule_path}: {rule_id} scenarios must be a non-empty list"
            )

        parsed: set[CheckScenario] = set()
        for value in raw_value:
            if not isinstance(value, str) or not value.strip():
                raise RuleConfigurationError(
                    f"{self._rule_path}: {rule_id} scenarios must contain non-empty strings"
                )
            try:
                scenario = CheckScenario(value)
            except ValueError as error:
                raise RuleConfigurationError(
                    f"{self._rule_path}: {rule_id} scenario {value!r} is unknown"
                ) from error
            if scenario not in allowed_scenarios:
                raise RuleConfigurationError(
                    f"{self._rule_path}: {rule_id} scenario {value!r} is not enabled"
                )
            parsed.add(scenario)

        return frozenset(parsed)

    def _require_non_empty_string(
        self,
        payload: dict[str, object],
        key: str,
        path: Path,
        *,
        context: str | None = None,
    ) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            prefix = f"{context} " if context is not None else ""
            raise RuleConfigurationError(
                f"{path}: {prefix}{key} must be a non-empty string"
            )
        return value

    def _optional_non_empty_string(
        self,
        payload: dict[str, object],
        key: str,
        path: Path,
        *,
        context: str | None = None,
    ) -> str | None:
        value = payload.get(key)
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            prefix = f"{context} " if context is not None else ""
            raise RuleConfigurationError(
                f"{path}: {prefix}{key} must be a non-empty string when provided"
            )
        return value
