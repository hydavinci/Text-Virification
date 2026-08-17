from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TerritoryStandardRule:
    bad: str
    good: str
    note: str


@dataclass(frozen=True)
class AdvertisingDictionary:
    version: str
    description: str
    extreme_words: tuple[str, ...]


@dataclass(frozen=True)
class ComplianceDictionary:
    version: str
    description: str
    politics: tuple[str, ...]
    ethnic_religion: tuple[str, ...]
    territory_standard: tuple[TerritoryStandardRule, ...]


@dataclass(frozen=True)
class SharedDictionaries:
    advertising: AdvertisingDictionary
    compliance: ComplianceDictionary


EMPTY_SHARED_DICTIONARIES = SharedDictionaries(
    advertising=AdvertisingDictionary(
        version="",
        description="",
        extreme_words=(),
    ),
    compliance=ComplianceDictionary(
        version="",
        description="",
        politics=(),
        ethnic_religion=(),
        territory_standard=(),
    ),
)
