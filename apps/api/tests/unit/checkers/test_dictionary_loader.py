import json
from pathlib import Path

import pytest

from text_verification.checkers.dictionary_loader import (
    DictionaryConfigurationError,
    DictionaryLoader,
)


def test_dictionary_loader_loads_approved_repository_resources() -> None:
    repository_root = Path(__file__).resolve().parents[5]

    dictionaries = DictionaryLoader(repository_root / "resources" / "dictionaries").load()

    assert dictionaries.advertising.version == "2026-08"
    assert "最高级" in dictionaries.advertising.extreme_words
    assert dictionaries.compliance.version == "2026-08-13"
    assert dictionaries.compliance.territory_standard[0].good == "中国香港"


def test_dictionary_loader_rejects_invalid_data_with_safe_public_error(
    tmp_path: Path,
) -> None:
    (tmp_path / "advertising-extreme-terms.zh-cn.json").write_text(
        json.dumps(
            {
                "version": "1",
                "description": "test",
                "extreme_words": ["最高级", ""],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "compliance-sensitive-rules.zh-cn.json").write_text(
        json.dumps(
            {
                "version": "1",
                "description": "test",
                "politics": [],
                "ethnic_religion": [],
                "territory_standard": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(DictionaryConfigurationError) as raised:
        DictionaryLoader(tmp_path).load()

    assert raised.value.code == "invalid_dictionary_configuration"
    assert raised.value.public_message == "共享词库配置无效，请联系管理员检查词库资源。"
    assert str(tmp_path) not in raised.value.public_message
    assert "extreme_words" in str(raised.value)
