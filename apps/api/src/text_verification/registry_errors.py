from __future__ import annotations


class MissingCapabilityError(LookupError):
    def __init__(self, kind: str, key: str) -> None:
        super().__init__(f"No {kind} registered for {key}.")
        self.kind = kind
        self.key = key


class DuplicateCapabilityError(ValueError):
    def __init__(self, kind: str, key: str) -> None:
        super().__init__(f"Duplicate {kind} registered for {key}.")
        self.kind = kind
        self.key = key
