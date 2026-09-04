from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from docx import Document

from text_verification.compatibility import exporters
from text_verification.compatibility.exporters import export_original


def test_tracked_docx_export_is_byte_deterministic_across_wall_clock_changes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source.docx"
    document = Document()
    document.add_paragraph("帐号测试")
    document.save(source)
    times = iter(
        [
            datetime(2026, 9, 4, 1, 0, tzinfo=UTC),
            datetime(2026, 9, 4, 2, 0, tzinfo=UTC),
        ]
    )

    class ChangingDateTime:
        @classmethod
        def now(cls, tz=None):
            del cls, tz
            return next(times)

    monkeypatch.setattr(
        exporters,
        "datetime",
        ChangingDateTime,
        raising=False,
    )

    first = export_original(
        source,
        "docx",
        [],
        True,
        original_text="帐号测试",
        modified_text="账号测试",
    )
    second = export_original(
        source,
        "docx",
        [],
        True,
        original_text="帐号测试",
        modified_text="账号测试",
    )

    assert first.content == second.content
