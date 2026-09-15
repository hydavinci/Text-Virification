from dataclasses import replace

import pytest

from text_verification.compatibility.adapters import text_to_document_model
from text_verification.domain.documents import FileType
from text_verification.domain.issues import IssueLimitExceededError
from text_verification.domain.ports import CheckContext
from text_verification.scenarios.models import Finding, RuleSpec
from text_verification.scenarios.registry import get_profile


def test_specialist_budget_rejects_excess_findings(monkeypatch) -> None:
    from text_verification.scenarios import checker

    profile = replace(get_profile("general"), rules=(
        RuleSpec("scenario.general.test", "test", "test",
                 lambda _: (Finding(0, 1, "first"), Finding(1, 2, "second"))),
    ))
    monkeypatch.setattr(checker, "get_profile", lambda _: profile)
    document = text_to_document_model(text="正文", source_name="x", file_type=FileType.TXT)
    with pytest.raises(IssueLimitExceededError):
        checker.check_scenario(document, CheckContext(), max_issues=1)


def test_uncertain_extraction_does_not_execute_absence_checks(monkeypatch) -> None:
    from text_verification.scenarios import checker

    def must_not_execute(_):
        raise AssertionError("an incomplete extraction cannot prove a missing target")

    profile = replace(get_profile("general"), rules=(
        RuleSpec("scenario.general.test", "test", "test",
                 must_not_execute, requires_complete_structure=True),
    ))
    monkeypatch.setattr(checker, "get_profile", lambda _: profile)
    document = text_to_document_model(text="正文", source_name="x", file_type=FileType.PDF)
    assert checker.check_scenario(document, CheckContext()) == []


def test_specialist_invalid_source_span_is_an_error_not_a_silent_drop(monkeypatch) -> None:
    from text_verification.scenarios import checker

    profile = replace(get_profile("general"), rules=(
        RuleSpec("scenario.general.test", "test", "test", lambda _: (Finding(0, 90, "bad"),)),
    ))
    monkeypatch.setattr(checker, "get_profile", lambda _: profile)
    document = text_to_document_model(text="正文", source_name="x", file_type=FileType.TXT)
    with pytest.raises(ValueError, match="span"):
        checker.check_scenario(document, CheckContext())
