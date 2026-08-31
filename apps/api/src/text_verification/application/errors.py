from __future__ import annotations

from typing import Any


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


class ReviewerError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        retryable: bool,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.metadata = dict(metadata or {})
