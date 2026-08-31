from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from text_verification.compatibility import llm_review
from text_verification.compatibility.analyzer import Issue, TextAnalyzer
from text_verification.compatibility.statistics import text_statistics
from text_verification.config import Settings

_CASES_PATH = Path(__file__).with_name("cases") / "source_rules.json"
_STATISTICS_CASES_PATH = Path(__file__).with_name("cases") / "source_statistics.json"
_LLM_FALLBACK_CASES_PATH = Path(__file__).with_name("cases") / "llm_fallback.json"
_REQUIRED_CASE_NAMES = {
    "identity number ending in X",
    "identity number ending in lowercase x",
    "punctuation wins width conflict",
    "business scenario filters colloquial wording",
    "security switch is independent",
    "sensitive switch is independent",
    "advertising switch is independent",
    "custom glossary replacement",
    "banned word detection",
    "representative character rule",
    "representative vocabulary rule",
    "representative sentence rule",
    "representative format rule",
    "representative discourse rule",
    "representative compliance rule",
}


def _contract_cases() -> list[Any]:
    raw_cases = json.loads(_CASES_PATH.read_text(encoding="utf-8"))
    return [
        pytest.param(rule_id, case, id=f"{rule_id}:{case['name']}")
        for rule_id, cases in raw_cases.items()
        for case in cases
    ]


def _statistics_cases() -> list[Any]:
    return [
        pytest.param(case, id=case["name"])
        for case in json.loads(_STATISTICS_CASES_PATH.read_text(encoding="utf-8"))
    ]


def _llm_fallback_cases() -> list[Any]:
    return [
        pytest.param(case, id=case["name"])
        for case in json.loads(_LLM_FALLBACK_CASES_PATH.read_text(encoding="utf-8"))
    ]


def test_source_rule_contract_inventory_covers_preserved_families_and_interactions() -> None:
    raw_cases = json.loads(_CASES_PATH.read_text(encoding="utf-8"))
    case_names = {
        case["name"]
        for cases in raw_cases.values()
        for case in cases
    }

    assert _REQUIRED_CASE_NAMES <= case_names


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
    actual_rule_ids = {issue.rule_id for issue in issues}
    assert set(case.get("required_rule_ids", ())) <= actual_rule_ids
    assert not set(case.get("absent_rule_ids", ())) & actual_rule_ids


@pytest.mark.parametrize("case", _statistics_cases())
def test_source_statistics_contract(case: dict[str, Any]) -> None:
    assert text_statistics(case["text"]) == case["expected"]


@pytest.mark.parametrize("case", _llm_fallback_cases())
def test_llm_fallback_preserves_local_issues(
    case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ContractCompletions:
        def create(self, **kwargs: object) -> object:
            del kwargs
            if case["behavior"] == "raise":
                raise TimeoutError("internal provider timeout detail")
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="not valid json"),
                    )
                ]
            )

    class ContractOpenAI:
        def __init__(self, **kwargs: object) -> None:
            del kwargs
            self.chat = SimpleNamespace(completions=ContractCompletions())

    issue = Issue(
        type="punctuation",
        severity="warning",
        original="，，",
        suggestion="，",
        position=2,
        end_position=4,
        context="测试，，内容",
        description="连续重复标点",
        rule_id="repeat_punct",
        layer="format",
    )
    before = issue.to_dict()
    monkeypatch.setattr(llm_review, "OpenAI", ContractOpenAI)

    reviewed, stats = llm_review.review_issues(
        Settings(llm_api_key="configured"),
        "测试，，内容",
        [issue],
    )

    assert [item.to_dict() for item in reviewed] == [before]
    assert stats["failed"] is True
    assert stats["failure_code"] == case["failure_code"]
    assert stats["reason"] == case["reason"]
