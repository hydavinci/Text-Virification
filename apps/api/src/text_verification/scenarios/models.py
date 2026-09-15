from __future__ import annotations

import re
from bisect import bisect_left
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from typing import Literal

from text_verification.compatibility.text_context import TextContext


@dataclass(frozen=True)
class RuleInput:
    text: str
    complete_structure: bool = False
    glossary_terms: frozenset[str] = frozenset()
    context: TextContext = field(init=False, repr=False)
    _quotes: tuple[tuple[int, int], ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "context", TextContext.build(self.text))
        ranges = [
            match.span()
            for match in re.finditer(r'"[^"]*"|“[^“”]*”|‘[^‘’]*’|「[^「」]*」', self.text)
        ]
        offset = 0
        block_start: int | None = None
        for line in self.text.splitlines(keepends=True):
            if re.match(r" {0,3}>", line):
                if block_start is None:
                    block_start = offset
            elif block_start is not None and not line.strip():
                ranges.append((block_start, offset))
                block_start = None
            offset += len(line)
        if block_start is not None:
            ranges.append((block_start, len(self.text)))
        merged: list[tuple[int, int]] = []
        for start, end in sorted(ranges):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        object.__setattr__(self, "_quotes", tuple(merged))

    def is_prose(self, start: int, end: int) -> bool:
        index = bisect_left(self._quotes, (end,)) - 1
        overlaps_quote = index >= 0 and self._quotes[index][1] > start
        return not self.context.is_protected(start, end) and not overlaps_quote

    def prose_matches(self, pattern: re.Pattern[str]) -> Iterator[re.Match[str]]:
        for match in pattern.finditer(self.text):
            if self.is_prose(*match.span()):
                yield match

    def lines(self) -> Iterator[tuple[int, int, str]]:
        for match in re.finditer(r"[^\n]+", self.text):
            yield match.start(), match.end(), match.group()


@dataclass(frozen=True)
class Finding:
    start: int
    end: int
    description: str
    type: str = "expression"
    severity: Literal["error", "warning", "info"] = "warning"
    confidence: float = 0.85


@dataclass(frozen=True)
class RuleSpec:
    rule_id: str
    name: str
    description: str
    check: Callable[[RuleInput], Iterable[Finding]]
    requires_complete_structure: bool = False
    allow_technical: bool = False


@dataclass(frozen=True)
class ScenarioProfile:
    id: str
    name: str
    description: str
    base_checks: tuple[str, ...]
    extended_checks: tuple[str, ...]
    rules: tuple[RuleSpec, ...]
    semantic_guidance: str
    version: str = "1"
