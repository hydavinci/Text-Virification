from __future__ import annotations


class VerificationError(RuntimeError):
    def __init__(
        self,
        code: str,
        stage: str,
        message: str,
        retryable: bool,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.message = message
        self.retryable = retryable
