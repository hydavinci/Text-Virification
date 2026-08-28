from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import TypeAdapter, ValidationError

from text_verification.compatibility.analyzer import SCENARIO_CONFIG, TextAnalyzer
from text_verification.compatibility.llm_review import (
    is_llm_review_enabled,
    review_issues,
)
from text_verification.compatibility.models import GlossaryTerm, Scenario
from text_verification.compatibility.parser import get_supported_formats, parse_file
from text_verification.compatibility.statistics import text_statistics

_ANALYZER = TextAnalyzer()  # type: ignore[no-untyped-call]
_GLOSSARY_ADAPTER = TypeAdapter(list[GlossaryTerm])
_BANNED_WORDS_ADAPTER = TypeAdapter(list[str])


class AnalysisInputError(ValueError):
    pass


def parse_glossary(value: str) -> list[dict[str, str]]:
    if not value.strip():
        return []
    try:
        terms = _GLOSSARY_ADAPTER.validate_python(json.loads(value))
    except (json.JSONDecodeError, ValidationError) as error:
        raise AnalysisInputError(
            "custom_glossary must be a JSON array of glossary terms."
        ) from error
    return [term.model_dump() for term in terms if term.original != term.standard]


def parse_banned_words(value: str) -> list[str]:
    if not value.strip():
        return []
    try:
        words = _BANNED_WORDS_ADAPTER.validate_python(json.loads(value))
    except (json.JSONDecodeError, ValidationError) as error:
        raise AnalysisInputError("banned_words must be a JSON array of strings.") from error
    return list(dict.fromkeys(word.strip() for word in words if word.strip()))


def analyze(
    *,
    text: str,
    filename: str,
    file_id: UUID | None,
    file_extension: str | None,
    scenario: Scenario,
    custom_glossary: list[dict[str, str]],
    banned_words: list[str],
    enable_security: bool,
    enable_sensitive: bool,
    enable_ad_extreme: bool,
) -> dict[str, Any]:
    issues = _ANALYZER.analyze(
        text,
        scenario=scenario.value,
        custom_glossary=custom_glossary,
        banned_words=banned_words,
        enable_security=enable_security,
        enable_sensitive=enable_sensitive,
        enable_ad_extreme=enable_ad_extreme,
    )

    review_stats: dict[str, Any] | None = None
    if is_llm_review_enabled():
        issues, review_stats = review_issues(text, issues)

    summary: dict[str, Any] = _ANALYZER.get_summary(issues)
    if review_stats is not None:
        summary["llm_review"] = review_stats

    return {
        "success": True,
        "filename": filename,
        "text": text,
        "stats": text_statistics(text),
        "issues": [issue.to_dict() for issue in issues],
        "summary": summary,
        "file_id": str(file_id) if file_id is not None else None,
        "file_ext": f".{file_extension}" if file_extension else None,
        "scenario": scenario.value,
    }


def parse_uploaded_file(path: Path, extension: str) -> str:
    text, _, _ = parse_file(str(path), extension, str(path.parent))
    if not text.strip():
        raise AnalysisInputError("File content is empty or no text could be extracted.")
    return text


def scenarios() -> list[dict[str, str]]:
    return [
        {
            "id": scenario.value,
            "name": str(SCENARIO_CONFIG[scenario.value]["name"]),
            "description": str(SCENARIO_CONFIG[scenario.value]["description"]),
        }
        for scenario in Scenario
    ]


def formats() -> list[dict[str, str]]:
    return list(get_supported_formats())
