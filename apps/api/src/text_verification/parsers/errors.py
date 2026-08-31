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
