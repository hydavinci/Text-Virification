from importlib import import_module
from typing import TYPE_CHECKING, Any

from text_verification.document_processing.pdf_models import PdfPageKind

if TYPE_CHECKING:
    from text_verification.document_processing.errors import (
        OcrLayoutError,
        OcrOutputError,
        OcrProcessingError,
        OcrUnavailableError,
    )
    from text_verification.document_processing.ocr_provider import (
        OcrProvider,
        OcrRecognizer,
        OcrTextBox,
    )

__all__ = [
    "OcrLayoutError",
    "OcrOutputError",
    "OcrProcessingError",
    "OcrProvider",
    "OcrRecognizer",
    "OcrTextBox",
    "OcrUnavailableError",
    "PdfPageKind",
]


def __getattr__(name: str) -> Any:
    if name in {
        "OcrLayoutError",
        "OcrOutputError",
        "OcrProcessingError",
        "OcrUnavailableError",
    }:
        module = import_module("text_verification.document_processing.errors")
    elif name in {"OcrProvider", "OcrRecognizer", "OcrTextBox"}:
        module = import_module("text_verification.document_processing.ocr_provider")
    else:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        )
    value = getattr(module, name)
    globals()[name] = value
    return value
