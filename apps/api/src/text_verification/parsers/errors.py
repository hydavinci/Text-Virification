from __future__ import annotations

from typing import Literal

CompatibilityDetailFormat = Literal["direct", "prefixed"]


class ParserError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        compatibility_detail: str | None = None,
        compatibility_detail_format: CompatibilityDetailFormat = "prefixed",
    ) -> None:
        super().__init__(message)
        self.compatibility_detail = compatibility_detail
        self.compatibility_detail_format = compatibility_detail_format


class PdfResourceLimitError(ParserError):
    def __init__(self, *, limit: str, maximum: int, actual: int) -> None:
        super().__init__(
            f"PDF exceeds the {limit} limit ({actual} > {maximum}).",
            compatibility_detail=f"PDF exceeds the {limit} limit.",
            compatibility_detail_format="direct",
        )
        self.limit = limit
        self.maximum = maximum
        self.actual = actual
