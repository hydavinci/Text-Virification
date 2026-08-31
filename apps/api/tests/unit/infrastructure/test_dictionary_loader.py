from __future__ import annotations

import hashlib
import os
from importlib.resources import as_file, files
from pathlib import Path

import pytest


def test_dictionary_snapshot_uses_packaged_bytes_for_deterministic_version() -> None:
    from text_verification.infrastructure.dictionary_loader import DictionaryLoader

    loader = DictionaryLoader()
    snapshot = loader.load("sensitive_rules")

    resource = files("text_verification.resources").joinpath("dictionaries", "sensitive_rules.json")
    with as_file(resource) as resource_path:
        expected_version = hashlib.sha256(resource_path.read_bytes()).hexdigest()

    assert snapshot.name == "sensitive_rules"
    assert snapshot.version == expected_version
    assert not hasattr(snapshot, "raw_bytes")


def test_dictionary_loader_returns_validated_immutable_entries() -> None:
    from text_verification.infrastructure.dictionary_loader import DictionaryLoader

    snapshot = DictionaryLoader().load("ad_extreme_words")

    assert snapshot.entries.extreme_words
    assert isinstance(snapshot.entries.extreme_words, tuple)
    with pytest.raises(AttributeError):
        snapshot.entries.extreme_words.append("额外词语")  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("name", "payload"),
    [
        ("sensitive_rules", "[]"),
        ("ad_extreme_words", "[]"),
        (
            "sensitive_rules",
            '{"politics":[1],"ethnic_religion":[],"territory_standard":[]}',
        ),
        (
            "sensitive_rules",
            '{"politics":[],"ethnic_religion":[],"territory_standard":["bad"]}',
        ),
        (
            "sensitive_rules",
            '{"politics":[],"ethnic_religion":[],"territory_standard":[{"bad":"台湾"}]}',
        ),
        ("ad_extreme_words", '{"extreme_words":[1]}'),
    ],
)
def test_dictionary_loader_rejects_malformed_dictionary_shapes(
    tmp_path: Path,
    name: str,
    payload: str,
) -> None:
    from text_verification.infrastructure.dictionary_loader import (
        DictionaryLoader,
        DictionaryLoadError,
    )

    (tmp_path / f"{name}.json").write_text(payload, encoding="utf-8")

    with pytest.raises(DictionaryLoadError, match=name):
        DictionaryLoader(root=tmp_path).load(name)


def test_dictionary_loader_reloads_when_content_changes_without_metadata_change(
    tmp_path: Path,
) -> None:
    from text_verification.infrastructure.dictionary_loader import DictionaryLoader

    path = tmp_path / "sensitive_rules.json"
    first = '{"politics":["甲"],"ethnic_religion":[],"territory_standard":[]}'
    second = '{"politics":["乙"],"ethnic_religion":[],"territory_standard":[]}'
    assert len(first.encode("utf-8")) == len(second.encode("utf-8"))

    path.write_text(first, encoding="utf-8")
    os.utime(path, (1_720_000_000, 1_720_000_000))
    loader = DictionaryLoader(root=tmp_path)
    initial = loader.load("sensitive_rules")

    path.write_text(second, encoding="utf-8")
    os.utime(path, (1_720_000_000, 1_720_000_000))
    updated = loader.load("sensitive_rules")

    assert initial.version != updated.version
    assert initial.entries.politics == ("甲",)
    assert updated.entries.politics == ("乙",)
