from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from text_verification.compatibility.analyzer import TextAnalyzer

_CASES_PATH = Path(__file__).with_name("cases") / "source_rules.json"


def _contract_cases() -> list[Any]:
    raw_cases = json.loads(_CASES_PATH.read_text(encoding="utf-8"))
    return [
        pytest.param(rule_id, case, id=f"{rule_id}:{case['name']}")
        for rule_id, cases in raw_cases.items()
        for case in cases
    ]


@pytest.mark.parametrize(("rule_id", "case"), _contract_cases())
def test_source_rule_contract(rule_id: str, case: dict[str, Any]) -> None:
    text = case["text"]
    analyzer = TextAnalyzer()

    issues = analyzer.analyze(text, **case.get("options", {}))

    assert [(issue.position, issue.end_position) for issue in issues] == sorted(
        (issue.position, issue.end_position) for issue in issues
    )
    assert len(
        {(issue.type, issue.position, issue.end_position, issue.original) for issue in issues}
    ) == len(issues)

    for issue in issues:
        assert 0 <= issue.position < issue.end_position <= len(text)
        assert issue.original == text[issue.position : issue.end_position]

    actual = [
        {
            "type": issue.type,
            "original": issue.original,
            "position": issue.position,
            "end_position": issue.end_position,
        }
        for issue in issues
        if issue.rule_id == rule_id
    ]

    assert actual == case["expected"]
