from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from text_verification.compatibility.adapters import text_to_document_model
from text_verification.compatibility.analyzer import TextAnalyzer
from text_verification.domain.documents import FileType
from text_verification.domain.issues import MAX_VERIFICATION_ISSUES
from text_verification.domain.ports import CheckContext
from text_verification.domain.verification import VerificationOptions
from text_verification.scenarios.checker import check_scenario


class ExpectedFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: int = Field(ge=0)
    end: int = Field(gt=0)
    type: str
    suggestion: str | None


class QualityCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    group: str
    split: Literal["regression", "holdout"]
    text: str
    options: VerificationOptions = VerificationOptions(
        enable_security=False, enable_sensitive=False, enable_extended_rules=True,
    )
    expected: list[ExpectedFinding]

    @model_validator(mode="after")
    def validate_labels(self) -> QualityCase:
        if self.options.enable_semantic_discovery:
            raise ValueError("Detection evaluation is local-only; disable semantic discovery.")
        for finding in self.expected:
            if not finding.start < finding.end <= len(self.text):
                raise ValueError("Expected finding range is outside source text.")
        return self


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _metrics(counts: dict[str, int]) -> dict[str, int | float | None]:
    tp, fp, fn = (
        counts["true_positives"], counts["false_positives"], counts["false_negatives"],
    )
    return {
        **counts,
        "precision": _rate(tp, tp + fp),
        "recall": _rate(tp, tp + fn),
        "suggestion_accuracy": _rate(counts["correct_suggestions"], tp),
        "source_span_validity": _rate(counts["valid_spans"], tp + fp),
        "false_positives_per_1000_chars": _rate(fp * 1000, counts["characters"]),
    }


def evaluate(cases: list[QualityCase]) -> dict[str, object]:
    analyzer = TextAnalyzer()
    grouped: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    overall: dict[str, int] = defaultdict(int)
    for case in cases:
        options = case.options
        predictions = analyzer.analyze(
            case.text, scenario=options.scenario.value,
            enable_security=options.enable_security,
            enable_sensitive=options.enable_sensitive,
            enable_ad_extreme=options.enable_ad_extreme,
            enable_extended_rules=options.enable_extended_rules,
            custom_glossary=[term.model_dump() for term in options.custom_glossary],
            banned_words=list(options.banned_words),
        )
        predictions.extend(check_scenario(
            text_to_document_model(text=case.text, source_name=case.name, file_type=FileType.TXT),
            CheckContext.from_options(options),
            max_issues=MAX_VERIFICATION_ISSUES - len(predictions),
        ))
        remaining = list(case.expected)
        counts = {
            "cases": 1, "characters": len(case.text), "true_positives": 0,
            "false_positives": 0, "false_negatives": 0, "correct_suggestions": 0,
            "valid_spans": 0,
        }
        for prediction in predictions:
            counts["valid_spans"] += int(
                0 <= prediction.position < prediction.end_position <= len(case.text)
                and prediction.original == case.text[
                    prediction.position:prediction.end_position
                ]
            )
            match = next((
                finding for finding in remaining
                if (finding.start, finding.end, finding.type)
                == (prediction.position, prediction.end_position, prediction.type)
            ), None)
            if match is None:
                counts["false_positives"] += 1
            else:
                counts["true_positives"] += 1
                counts["correct_suggestions"] += int(prediction.suggestion == match.suggestion)
                remaining.remove(match)
        counts["false_negatives"] = len(remaining)
        for key, value in counts.items():
            overall[key] += value
            grouped[case.group][key] += value
    return {
        "overall": _metrics(overall),
        "groups": {name: _metrics(counts) for name, counts in sorted(grouped.items())},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline, exact-span detection evaluation.")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--split", choices=("regression", "holdout", "all"), default="holdout")
    args = parser.parse_args()
    cases = TypeAdapter(list[QualityCase]).validate_json(args.dataset.read_text(encoding="utf-8"))
    selected = [case for case in cases if args.split == "all" or case.split == args.split]
    if not selected:
        parser.error("No cases match the selected split.")
    print(json.dumps(evaluate(selected), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
