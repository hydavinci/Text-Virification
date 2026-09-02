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


class OcrLayoutError(ValueError):
    pass
