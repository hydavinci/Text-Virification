from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from text_verification.application.errors import VerificationError
from text_verification.application.factory import build_default_verification_pipeline
from text_verification.application.verification_pipeline import VerificationCommand
from text_verification.config import Settings
from text_verification.document_processing import ocr_provider as ocr_provider_module
from text_verification.document_processing.ocr_provider import OcrTextBox
from text_verification.domain.documents import FileType
from text_verification.domain.verification import (
    VerificationExecutionMode,
    VerificationOptions,
)

FIXTURE_DIRECTORY = Path(__file__).resolve().parents[2] / "fixtures" / "pdf"


def _command(
    fixture: str,
    *,
    execution_mode: VerificationExecutionMode = VerificationExecutionMode.SYNCHRONOUS,
) -> VerificationCommand:
    return VerificationCommand(
        document_id=uuid4(),
        source_path=FIXTURE_DIRECTORY / fixture,
        direct_text=None,
        source_name=fixture,
        file_type=FileType.PDF,
        options=VerificationOptions(enable_security=False, enable_sensitive=False),
        execution_mode=execution_mode,
    )


def test_default_pipeline_defers_optional_ocr_import_until_scan_requires_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imported: list[str] = []

    def unavailable_import(name: str) -> object:
        imported.append(name)
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(ocr_provider_module.importlib, "import_module", unavailable_import)
    pipeline = build_default_verification_pipeline(Settings(llm_api_key=""))

    text_result = pipeline.run(_command("text-page.pdf"))

    assert text_result.text.startswith("Structured text page")
    assert imported == []

    with pytest.raises(VerificationError) as raised:
        pipeline.run(
            _command(
                "scanned-page.pdf",
                execution_mode=VerificationExecutionMode.ASYNCHRONOUS,
            )
        )

    assert raised.value.code == "ocr_unavailable"
    assert raised.value.stage == "ocr"
    assert raised.value.retryable is False
    assert imported == ["rapidocr"]


def test_default_pipeline_reports_typed_ocr_error_for_mixed_pdf_without_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable_import(name: str) -> object:
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(ocr_provider_module.importlib, "import_module", unavailable_import)
    pipeline = build_default_verification_pipeline(Settings(llm_api_key=""))

    with pytest.raises(VerificationError) as raised:
        pipeline.run(
            _command(
                "mixed-page.pdf",
                execution_mode=VerificationExecutionMode.ASYNCHRONOUS,
            )
        )

    assert raised.value.code == "ocr_unavailable"
    assert raised.value.stage == "ocr"
    assert raised.value.retryable is False


def test_default_pipeline_selects_ocr_language_per_request_without_state_leakage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    languages: list[str] = []

    def recognize(self, image: object, language: str) -> list[OcrTextBox]:
        del self, image
        languages.append(language)
        return [
            OcrTextBox(
                text="recognized",
                confidence=0.99,
                bbox=((20.0, 20.0), (180.0, 20.0), (180.0, 45.0), (20.0, 45.0)),
            )
        ]

    monkeypatch.setattr(ocr_provider_module.OcrProvider, "recognize", recognize)
    pipeline = build_default_verification_pipeline(Settings(llm_api_key=""))

    for language in ("en", "ja", "zh"):
        command = _command(
            "scanned-page.pdf",
            execution_mode=VerificationExecutionMode.ASYNCHRONOUS,
        )
        pipeline.run(
            VerificationCommand(
                **{
                    **command.__dict__,
                    "options": VerificationOptions(
                        ocr_language=language,
                        enable_security=False,
                        enable_sensitive=False,
                    ),
                }
            )
        )

    assert languages == ["en", "ja", "zh"]
