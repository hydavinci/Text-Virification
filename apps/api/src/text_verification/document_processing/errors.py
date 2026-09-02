from __future__ import annotations


class OcrUnavailableError(RuntimeError):
    def __init__(
        self,
        message: str = "OCR is unavailable in the current environment.",
        *,
        code: str = "ocr_unavailable",
        stage: str = "ocr",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.message = message
        self.retryable = retryable


class OcrOutputError(ValueError):
    pass


class OcrProcessingError(RuntimeError):
    def __init__(
        self,
        message: str = "OCR processing failed.",
        *,
        code: str = "ocr_failed",
        stage: str = "ocr",
        retryable: bool = True,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.message = message
        self.retryable = retryable


class OcrLayoutError(ValueError):
    pass
