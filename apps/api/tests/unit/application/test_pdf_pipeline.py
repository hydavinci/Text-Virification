from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from text_verification.application.errors import VerificationError
from text_verification.application.factory import build_default_verification_pipeline
from text_verification.application.verification_pipeline import VerificationCommand
from text_verification.config import Settings
from text_verification.domain.documents import FileType
from text_verification.domain.verification import (
    VerificationExecutionMode,
    VerificationOptions,
)

FIXTURE_DIRECTORY = Path(__file__).resolve().parents[2] / "fixtures" / "pdf"


def _command(fixture: str) -> VerificationCommand:
    return VerificationCommand(
        document_id=uuid4(),
        source_path=FIXTURE_DIRECTORY / fixture,
        direct_text=None,
        source_name=fixture,
        file_type=FileType.PDF,
        options=VerificationOptions(enable_security=False, enable_sensitive=False),
        execution_mode=VerificationExecutionMode.SYNCHRONOUS,
    )


def test_pipeline_rejects_scan_only_pdf_with_typed_ocr_requirement() -> None:
    pipeline = build_default_verification_pipeline(Settings(llm_api_key=""))

    with pytest.raises(VerificationError) as raised:
        pipeline.run(_command("scanned-page.pdf"))

    assert raised.value.code == "ocr_required"
    assert raised.value.stage == "ocr"


def test_pipeline_preserves_native_mixed_text_and_reports_partial_ocr_requirement() -> None:
    pipeline = build_default_verification_pipeline(Settings(llm_api_key=""))

    result = pipeline.run(_command("mixed-page.pdf"))

    assert result.text == "Readable overlay text\nThis native text must not trigger OCR."
    assert result.ocr_requirement is not None
    assert result.ocr_requirement.mode == "partial"
    assert result.ocr_requirement.pages == (1,)
    assert result.degradation.is_degraded is True
    assert result.degradation.reasons == ("ocr_required_pages",)
    assert result.metadata.pdf is not None
