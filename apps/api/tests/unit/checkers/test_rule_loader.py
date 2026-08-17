import json
from pathlib import Path

import pytest

from text_verification.checkers.models import CheckCategory, CheckScenario
from text_verification.checkers.rule_loader import RuleConfigurationError, RuleLoader


def test_rule_loader_rejects_unknown_category(tmp_path: Path) -> None:
    rule_path, scenario_path = write_rule_configuration(
        tmp_path,
        [{**valid_rule(), "category": "unknown"}],
    )

    with pytest.raises(RuleConfigurationError, match="unknown"):
        RuleLoader(rule_path, scenario_path).load()


def test_rule_loader_rejects_duplicate_ids(tmp_path: Path) -> None:
    rule_path, scenario_path = write_rule_configuration(
        tmp_path,
        [valid_rule(), valid_rule()],
    )

    with pytest.raises(RuleConfigurationError, match="duplicate rule id"):
        RuleLoader(rule_path, scenario_path).load()


def test_rule_loader_rejects_empty_pattern(tmp_path: Path) -> None:
    rule_path, scenario_path = write_rule_configuration(
        tmp_path,
        [{**valid_rule(), "pattern": "  "}],
    )

    with pytest.raises(RuleConfigurationError, match="pattern must be a non-empty string"):
        RuleLoader(rule_path, scenario_path).load()


def test_rule_loader_rejects_invalid_severity(tmp_path: Path) -> None:
    rule_path, scenario_path = write_rule_configuration(
        tmp_path,
        [{**valid_rule(), "severity": "urgent"}],
    )

    with pytest.raises(RuleConfigurationError, match="severity 'urgent' is invalid"):
        RuleLoader(rule_path, scenario_path).load()


def test_rule_loader_rejects_invalid_rule_scenario(tmp_path: Path) -> None:
    rule_path, scenario_path = write_rule_configuration(
        tmp_path,
        [{**valid_rule(), "scenarios": ["education"]}],
    )

    with pytest.raises(RuleConfigurationError, match="scenario 'education' is unknown"):
        RuleLoader(rule_path, scenario_path).load()


def test_rule_loader_loads_repository_rules() -> None:
    repository_root = Path(__file__).resolve().parents[5]
    rule_set = RuleLoader(
        repository_root / "resources" / "rules" / "common-rules.zh-cn.json",
        repository_root / "resources" / "rules" / "scenarios.zh-cn.json",
    ).load()

    assert rule_set.version
    assert {rule.category for rule in rule_set.rules} == set(CheckCategory)
    assert rule_set.allowed_scenarios == frozenset(CheckScenario)
    assert any(rule.id == "security-ad-001" for rule in rule_set.rules)


def test_check_scenarios_match_the_approved_contract_exactly() -> None:
    assert [scenario.value for scenario in CheckScenario] == [
        "general",
        "academic",
        "business",
        "legal",
        "news",
        "technical",
    ]


def write_rule_configuration(
    tmp_path: Path,
    rules: list[dict[str, object]],
) -> tuple[Path, Path]:
    scenario_path = tmp_path / "scenarios.json"
    scenario_path.write_text(
        json.dumps(
            {
                "version": "1",
                "scenarios": [
                    {"id": "general", "label": "通用"},
                    {"id": "academic", "label": "学术"},
                    {"id": "business", "label": "商务"},
                    {"id": "legal", "label": "法律"},
                    {"id": "news", "label": "新闻"},
                    {"id": "technical", "label": "技术"},
                ],
            }
        ),
        encoding="utf-8",
    )
    rule_path = tmp_path / "rules.json"
    rule_path.write_text(
        json.dumps({"version": "1", "rules": rules}),
        encoding="utf-8",
    )
    return rule_path, scenario_path


def valid_rule() -> dict[str, object]:
    return {
        "id": "x",
        "category": "security",
        "severity": "warning",
        "pattern": "绝对领先",
        "suggestion": "领先",
        "message": "避免使用绝对化表述。",
        "scenarios": ["general"],
        "auto_fixable": True,
    }
