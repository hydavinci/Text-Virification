from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from importlib.resources import as_file, files
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from text_verification.domain.dictionaries import (
    AdExtremeWordsEntries,
    DictionaryName,
    DictionarySnapshot,
    SensitiveRulesEntries,
)

_RESOURCE_PACKAGE = "text_verification.resources"
_RESOURCE_DIRECTORY = "dictionaries"
_RESOURCE_FILENAMES: dict[DictionaryName, str] = {
    "sensitive_rules": "sensitive_rules.json",
    "ad_extreme_words": "ad_extreme_words.json",
}
_ENTRY_ADAPTERS: dict[DictionaryName, TypeAdapter[object]] = {
    "sensitive_rules": TypeAdapter(SensitiveRulesEntries),
    "ad_extreme_words": TypeAdapter(AdExtremeWordsEntries),
}


class DictionaryLoadError(RuntimeError):
    pass


@dataclass(frozen=True)
class _CachedSnapshot:
    path: Path
    metadata: tuple[int, int]
    content_hash: str
    snapshot: DictionarySnapshot


class DictionaryLoader:
    def __init__(self, *, root: Path | None = None) -> None:
        self._root = root
        self._cache: dict[DictionaryName, _CachedSnapshot] = {}

    def load(self, name: DictionaryName) -> DictionarySnapshot:
        if self._root is not None:
            path = self._root / _filename_for(name)
            return self._load_from_path(name, path)

        resource = files(_RESOURCE_PACKAGE).joinpath(_RESOURCE_DIRECTORY, _filename_for(name))
        try:
            with as_file(resource) as path:
                return self._load_from_path(name, path)
        except FileNotFoundError as error:
            raise DictionaryLoadError(f"Dictionary '{name}' could not be found.") from error

    def _load_from_path(self, name: DictionaryName, path: Path) -> DictionarySnapshot:
        try:
            content = path.read_bytes()
            metadata = self._metadata_for(path)
            content_hash = sha256(content).hexdigest()
            cached = self._cache.get(name)
            if cached is not None and cached.path == path and cached.content_hash == content_hash:
                if cached.metadata != metadata:
                    self._cache[name] = _CachedSnapshot(
                        path,
                        metadata,
                        content_hash,
                        cached.snapshot,
                    )
                return cached.snapshot

            raw_payload = json.loads(content)
            entries = _ENTRY_ADAPTERS[name].validate_python(raw_payload)
        except FileNotFoundError as error:
            raise DictionaryLoadError(f"Dictionary '{name}' could not be found.") from error
        except (json.JSONDecodeError, ValidationError) as error:
            raise DictionaryLoadError(f"Dictionary '{name}' is invalid.") from error

        snapshot = DictionarySnapshot(name=name, version=content_hash, entries=entries)
        self._cache[name] = _CachedSnapshot(path, metadata, content_hash, snapshot)
        return snapshot

    @staticmethod
    def _metadata_for(path: Path) -> tuple[int, int]:
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_size


def _filename_for(name: DictionaryName) -> str:
    try:
        return _RESOURCE_FILENAMES[name]
    except KeyError as error:
        raise DictionaryLoadError(f"Unsupported dictionary '{name}'.") from error
