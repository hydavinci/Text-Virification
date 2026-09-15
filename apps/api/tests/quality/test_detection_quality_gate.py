from pathlib import Path

import pytest
from pydantic import TypeAdapter

from text_verification.evaluation import QualityCase, evaluate


@pytest.mark.parametrize("split", ["regression", "holdout"])
def test_curated_detection_gate(split: str) -> None:
    cases = TypeAdapter(list[QualityCase]).validate_json(
        Path(__file__).with_name("detection_cases.json").read_text(encoding="utf-8"),
    )
    report = evaluate([case for case in cases if case.split == split])
    metrics = report["overall"]
    assert metrics["precision"] >= 0.95, report
    assert metrics["recall"] >= 0.95, report
    assert metrics["suggestion_accuracy"] >= 0.95, report
    assert metrics["source_span_validity"] == 1, report
