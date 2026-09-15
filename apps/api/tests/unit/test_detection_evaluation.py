import pytest

from text_verification.evaluation import QualityCase, evaluate


def test_evaluation_counts_misses_and_extra_findings_instead_of_only_hits() -> None:
    cases = [
        QualityCase.model_validate({
            "name": "corrected spelling", "group": "english", "split": "regression",
            "text": "teh", "expected": [
                {"start": 0, "end": 3, "type": "typo", "suggestion": "the"},
            ],
        }),
        QualityCase.model_validate({
            "name": "intentional missing label", "group": "english", "split": "regression",
            "text": "adress", "expected": [],
        }),
        QualityCase.model_validate({
            "name": "intentional unreachable label", "group": "english", "split": "regression",
            "text": "fine", "expected": [
                {"start": 0, "end": 4, "type": "typo", "suggestion": "other"},
            ],
        }),
    ]
    report = evaluate(cases)
    assert report["overall"]["true_positives"] == 1
    assert report["overall"]["false_positives"] == 1
    assert report["overall"]["false_negatives"] == 1
    assert report["overall"]["precision"] == 0.5
    assert report["overall"]["recall"] == 0.5
    assert report["overall"]["suggestion_accuracy"] == 1.0
    assert report["overall"]["source_span_validity"] == 1.0
    assert report["overall"]["false_positives_per_1000_chars"] == pytest.approx(1000 / 13)
    assert report["groups"]["english"]["cases"] == 3


def test_evaluation_rejects_out_of_range_labels() -> None:
    with pytest.raises(ValueError, match="range"):
        QualityCase.model_validate({
            "name": "invalid", "group": "chinese", "split": "regression",
            "text": "短文",
            "expected": [{"start": 0, "end": 99, "type": "typo", "suggestion": "正文"}],
        })


def test_evaluation_reports_undefined_rates_explicitly() -> None:
    case = QualityCase.model_validate({
        "name": "negative", "group": "english", "split": "holdout",
        "text": "This is correct.", "expected": [],
    })
    report = evaluate([case])
    assert report["overall"]["precision"] is None
    assert report["overall"]["recall"] is None
    assert report["overall"]["suggestion_accuracy"] is None


def test_evaluation_does_not_count_wrong_suggestions_as_correct() -> None:
    case = QualityCase.model_validate({
        "name": "different desired fix", "group": "english", "split": "regression",
        "text": "teh",
        "expected": [{"start": 0, "end": 3, "type": "typo", "suggestion": "a"}],
    })
    report = evaluate([case])
    assert report["overall"]["true_positives"] == 1
    assert report["overall"]["suggestion_accuracy"] == 0


def test_local_evaluation_rejects_requested_semantic_discovery() -> None:
    with pytest.raises(ValueError, match="local-only"):
        QualityCase.model_validate({
            "name": "semantic request", "group": "english", "split": "holdout",
            "text": "A sentence.", "expected": [],
            "options": {"enable_semantic_discovery": True},
        })
