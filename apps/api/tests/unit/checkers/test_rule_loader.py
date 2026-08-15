import json
from pathlib import Path

import pytest

from text_verification.checkers.models import CheckCategory
from text_verification.checkers.rule_loader import RuleConfigurationError, RuleLoader


def test_rule_loader_rejects_unknown_category(tmp_path: Path) -> None:
    scenario_path = tmp_path / "scenarios.json"
    scenario_path.write_text(
        json.dumps(
            {
                "version": "1",
                "scenarios": [
                    {"id": "general", "label": "通用"},
                    {"id": "business", "label": "商务"},
                    {"id": "news", "label": "新闻"},
                    {"id": "legal", "label": "法务"},
                    {"id": "education", "label": "教育"},
                    {"id": "medical", "label": "医疗"},
                ],
            }
        ),
        encoding="utf-8",
    )
    rule_path = tmp_path / "rules.json"
    rule_path.write_text(
        json.dumps(
            {
                "version": "1",
                "rules": [
                    {
                        "id": "x",
                        "category": "unknown",
                        "severity": "warning",
                        "pattern": "绝对领先",
                        "suggestion": "领先",
                        "message": "避免使用绝对化表述。",
                        "scenarios": ["general"],
                        "auto_fixable": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuleConfigurationError, match="unknown"):
        RuleLoader(rule_path, scenario_path).load()


def test_rule_loader_loads_repository_rules() -> None:
    repository_root = Path(__file__).resolve().parents[5]
    rule_set = RuleLoader(
        repository_root / "resources" / "rules" / "common-rules.zh-cn.json",
        repository_root / "resources" / "rules" / "scenarios.zh-cn.json",
    ).load()

    assert rule_set.version
    assert {rule.category for rule in rule_set.rules} == set(CheckCategory)
    assert any(rule.id == "security-ad-001" for rule in rule_set.rules)
