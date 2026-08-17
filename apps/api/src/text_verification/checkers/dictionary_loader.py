from __future__ import annotations

import json
import re
from pathlib import Path

from text_verification.domain.dictionaries import (
    AdvertisingDictionary,
    ComplianceDictionary,
    SharedDictionaries,
    TerritoryStandardRule,
)

ADVERTISING_FILE_NAME = "advertising-extreme-terms.zh-cn.json"
COMPLIANCE_FILE_NAME = "compliance-sensitive-rules.zh-cn.json"


class DictionaryConfigurationError(ValueError):
    code = "invalid_dictionary_configuration"
    public_message = "共享词库配置无效，请联系管理员检查词库资源。"


class DictionaryLoader:
    def __init__(self, dictionaries_root: Path) -> None:
        self._root = dictionaries_root

    def load(self) -> SharedDictionaries:
        return SharedDictionaries(
            advertising=self._load_advertising(self._root / ADVERTISING_FILE_NAME),
            compliance=self._load_compliance(self._root / COMPLIANCE_FILE_NAME),
        )

    def _load_advertising(self, path: Path) -> AdvertisingDictionary:
        payload = self._read_json(path)
        return AdvertisingDictionary(
            version=self._required_string(payload, "version", path),
            description=self._required_string(payload, "description", path),
            extreme_words=self._string_list(
                payload.get("extreme_words"),
                "extreme_words",
                path,
                allow_empty=False,
            ),
        )

    def _load_compliance(self, path: Path) -> ComplianceDictionary:
        payload = self._read_json(path)
        raw_territory_rules = payload.get("territory_standard")
        if not isinstance(raw_territory_rules, list):
            raise DictionaryConfigurationError(f"{path}: territory_standard must be a list")

        territory_rules: list[TerritoryStandardRule] = []
        seen_patterns: set[str] = set()
        for index, raw_rule in enumerate(raw_territory_rules, start=1):
            if not isinstance(raw_rule, dict):
                raise DictionaryConfigurationError(
                    f"{path}: territory_standard[{index}] must be an object"
                )
            pattern = self._required_string(
                raw_rule,
                "bad",
                path,
                context=f"territory_standard[{index}]",
            )
            if pattern in seen_patterns:
                raise DictionaryConfigurationError(
                    f"{path}: duplicate territory pattern {pattern!r}"
                )
            seen_patterns.add(pattern)
            try:
                re.compile(pattern)
            except re.error as error:
                raise DictionaryConfigurationError(
                    f"{path}: territory pattern {pattern!r} is invalid"
                ) from error
            territory_rules.append(
                TerritoryStandardRule(
                    bad=pattern,
                    good=self._required_string(
                        raw_rule,
                        "good",
                        path,
                        context=f"territory_standard[{index}]",
                    ),
                    note=self._required_string(
                        raw_rule,
                        "note",
                        path,
                        context=f"territory_standard[{index}]",
                    ),
                )
            )

        return ComplianceDictionary(
            version=self._required_string(payload, "version", path),
            description=self._required_string(payload, "description", path),
            politics=self._string_list(payload.get("politics"), "politics", path),
            ethnic_religion=self._string_list(
                payload.get("ethnic_religion"),
                "ethnic_religion",
                path,
            ),
            territory_standard=tuple(territory_rules),
        )

    def _read_json(self, path: Path) -> dict[str, object]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except OSError as error:
            raise DictionaryConfigurationError(f"{path}: {error.strerror}") from error
        except json.JSONDecodeError as error:
            raise DictionaryConfigurationError(
                f"{path}: invalid JSON at line {error.lineno} column {error.colno}"
            ) from error
        if not isinstance(payload, dict):
            raise DictionaryConfigurationError(f"{path}: root must be an object")
        return payload

    def _required_string(
        self,
        payload: dict[str, object],
        key: str,
        path: Path,
        *,
        context: str | None = None,
    ) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            prefix = f"{context} " if context else ""
            raise DictionaryConfigurationError(
                f"{path}: {prefix}{key} must be a non-empty string"
            )
        return value

    def _string_list(
        self,
        value: object,
        key: str,
        path: Path,
        *,
        allow_empty: bool = True,
    ) -> tuple[str, ...]:
        if not isinstance(value, list) or (not allow_empty and not value):
            qualifier = "" if allow_empty else " non-empty"
            raise DictionaryConfigurationError(f"{path}: {key} must be a{qualifier} list")
        parsed: list[str] = []
        seen: set[str] = set()
        for index, item in enumerate(value, start=1):
            if not isinstance(item, str) or not item.strip():
                raise DictionaryConfigurationError(
                    f"{path}: {key}[{index}] must be a non-empty string"
                )
            if item in seen:
                raise DictionaryConfigurationError(f"{path}: duplicate {key} entry {item!r}")
            seen.add(item)
            parsed.append(item)
        return tuple(parsed)
