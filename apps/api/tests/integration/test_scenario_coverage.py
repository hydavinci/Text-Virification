from pathlib import Path
from uuid import uuid4

import pytest
from docx import Document

from text_verification.application.factory import build_default_verification_pipeline
from text_verification.application.verification_pipeline import VerificationCommand
from text_verification.checkers.compatibility_checker import CompatibilityChecker
from text_verification.compatibility.adapters import (
    text_to_document_model,
    verification_result_to_legacy_response,
)
from text_verification.compatibility.service import analyze
from text_verification.config import Settings
from text_verification.domain.documents import FileType
from text_verification.domain.ports import CheckContext
from text_verification.domain.verification import (
    Scenario,
    VerificationExecutionMode,
    VerificationOptions,
    VerificationResult,
)


def test_actual_docx_reports_skipped_checks_and_preserves_them_on_serialization(
    tmp_path: Path,
) -> None:
    source = tmp_path / "paper.docx"
    word = Document()
    word.add_paragraph("样本文本。")
    word.save(source)
    pipeline = build_default_verification_pipeline(Settings(_env_file=None, llm_api_key=""))
    result = pipeline.run(VerificationCommand(
        document_id=uuid4(), source_path=source, direct_text=None,
        source_name=source.name, file_type=FileType.DOCX,
        options=VerificationOptions(
            scenario=Scenario.ACADEMIC, enable_security=False, enable_sensitive=False,
        ),
        execution_mode=VerificationExecutionMode.SYNCHRONOUS,
    ))
    assert result.summary.total == 0
    assert result.degradation.is_degraded
    reasons = result.degradation.reasons
    assert {reason.split(":")[1] for reason in reasons} == {
        "scenario.academic.citation_reference", "scenario.academic.caption_reference",
    }
    assert all(reason.startswith("scenario_rule_skipped:") for reason in reasons)
    restored = VerificationResult.model_validate(result.model_dump(mode="json"))
    assert restored.degradation.reasons == reasons
    payload = verification_result_to_legacy_response(restored)
    assert payload["degradation"]["reasons"] == list(reasons)


def test_legacy_service_reports_the_same_incomplete_coverage() -> None:
    result = analyze(
        Settings(_env_file=None, llm_api_key=""), text="样本文本。",
        filename="paper.docx", file_id=None, file_extension="docx",
        scenario=Scenario.ACADEMIC, custom_glossary=[], banned_words=[],
        enable_security=False, enable_sensitive=False, enable_ad_extreme=False,
    )
    assert result.degradation.is_degraded
    assert len(result.degradation.reasons) == 2


def test_plain_text_does_not_claim_structural_checks_were_skipped() -> None:
    result = analyze(
        Settings(_env_file=None, llm_api_key=""), text="样本文本。",
        filename="paper.txt", file_id=None, file_extension="txt",
        scenario=Scenario.ACADEMIC, custom_glossary=[], banned_words=[],
        enable_security=False, enable_sensitive=False, enable_ad_extreme=False,
    )
    assert result.degradation.reasons == ()


@pytest.mark.parametrize("file_type", list(FileType))
@pytest.mark.parametrize(("scenario", "skipped_count"), [
    (Scenario.GENERAL, 0), (Scenario.ACADEMIC, 2), (Scenario.BUSINESS, 2),
    (Scenario.LEGAL, 2), (Scenario.NEWS, 0), (Scenario.TECHNICAL, 1),
])
def test_coverage_policy_is_consistent_for_every_type(
    file_type: FileType, scenario: Scenario, skipped_count: int,
) -> None:
    document = text_to_document_model(
        text="样本文本。", source_name="input", file_type=file_type,
    )
    result = CompatibilityChecker().check(document, CheckContext(
        scenario=scenario, enable_security=False, enable_sensitive=False,
    ))
    expected = 0 if file_type in {FileType.TXT, FileType.MARKDOWN} else skipped_count
    assert len(result.degradation_reasons) == expected
    assert all(
        reason.startswith(f"scenario_rule_skipped:scenario.{scenario.value}.")
        for reason in result.degradation_reasons
    )
