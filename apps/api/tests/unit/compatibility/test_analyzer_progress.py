from __future__ import annotations

import pytest

from text_verification.compatibility.analyzer import TextAnalyzer
from text_verification.domain.ports import VerificationProgressStage


def test_analyzer_notifies_real_check_boundaries_in_job_status_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operations: list[str] = []
    analyzer = TextAnalyzer()
    monkeypatch.setattr(
        analyzer,
        "_check_punctuation",
        lambda text: operations.append("work:format") or [],
    )
    monkeypatch.setattr(
        analyzer,
        "_check_pii",
        lambda text: operations.append("work:sensitive") or [],
    )
    monkeypatch.setattr(
        analyzer,
        "_check_chinese_typos",
        lambda text: operations.append("work:chinese") or [],
    )
    monkeypatch.setattr(
        analyzer,
        "_check_english_spelling",
        lambda text: operations.append("work:english") or [],
    )

    analyzer.analyze(
        "clean",
        enable_sensitive=False,
        progress_observer=lambda stage: operations.append(f"stage:{stage.value}"),
    )

    assert operations == [
        "stage:checking_format",
        "work:format",
        "stage:checking_sensitive",
        "work:sensitive",
        "stage:checking_chinese",
        "work:chinese",
        "stage:checking_english",
        "work:english",
    ]
    assert [stage.value for stage in VerificationProgressStage] == [
        "parsing",
        "ocr",
        "checking_format",
        "checking_sensitive",
        "checking_chinese",
        "checking_english",
    ]
