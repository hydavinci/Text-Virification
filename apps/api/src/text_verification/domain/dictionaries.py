from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

DictionaryName = Literal["sensitive_rules", "ad_extreme_words"]
_DictionaryVersion = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
_DictionaryText = Annotated[str, StringConstraints(strict=True, min_length=1)]


class TerritoryStandardEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    bad: _DictionaryText
    good: _DictionaryText
    note: _DictionaryText | None = None


class SensitiveRulesEntries(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    politics: tuple[_DictionaryText, ...]
    ethnic_religion: tuple[_DictionaryText, ...]
    territory_standard: tuple[TerritoryStandardEntry, ...]


class AdExtremeWordsEntries(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    extreme_words: tuple[_DictionaryText, ...]


class DictionarySnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: DictionaryName
    version: _DictionaryVersion
    entries: SensitiveRulesEntries | AdExtremeWordsEntries
