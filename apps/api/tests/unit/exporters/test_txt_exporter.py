from __future__ import annotations

from codecs import BOM_UTF8
from pathlib import Path
from uuid import UUID, uuid4

from text_verification.domain.documents import DocumentModel, FileType, TextBlock
from text_verification.exporters import ExportWarning, Replacement, ReplacementPlan, TxtExporter


def test_txt_export_applies_code_point_offsets_from_end(tmp_path: Path) -> None:
    target = tmp_path / "modified.txt"

    TxtExporter().export_text(
        "A😀绝对领先B",
        [Replacement("p-1", 2, 6, "绝对领先", "领先", uuid4())],
        target,
    )

    assert target.read_text(encoding="utf-8") == "A😀领先B"


def test_txt_export_reconstructs_blocks_with_single_blank_lines_and_one_final_newline(
    tmp_path: Path,
) -> None:
    document = build_document(["第一段", "第二段"])
    plan = ReplacementPlan(
        applicable=[
            Replacement(
                block_id="p-000002",
                start=0,
                end=3,
                original="第二段",
                value="末段",
                issue_id=UUID("00000000-0000-0000-0000-000000000001"),
            )
        ],
        warnings=[
            ExportWarning(
                code="missing_block",
                message="unused",
                issue_id=UUID("00000000-0000-0000-0000-000000000002"),
                block_id="missing",
            )
        ],
    )
    target = tmp_path / "modified.txt"

    TxtExporter().export(document, plan, target)

    payload = target.read_bytes()
    assert payload == "第一段\n\n末段\n".encode()
    assert not payload.startswith(BOM_UTF8)


def test_txt_export_sorts_replacements_descending_before_applying(tmp_path: Path) -> None:
    target = tmp_path / "modified.txt"

    TxtExporter().export_text(
        "abcdefg",
        [
            Replacement("p-1", 1, 3, "bc", "X", uuid4()),
            Replacement("p-1", 4, 6, "ef", "YZ", uuid4()),
        ],
        target,
    )

    assert target.read_text(encoding="utf-8") == "aXdYZg"


def build_document(block_texts: list[str]) -> DocumentModel:
    blocks = [
        TextBlock(
            block_id=f"p-{index + 1:06d}",
            kind="paragraph",
            text=text,
            page=None,
            paragraph_index=index,
            parent_id=None,
            style={"style_name": "Normal"},
            source_locator={"paragraph_index": index},
        )
        for index, text in enumerate(block_texts)
    ]
    return DocumentModel(
        document_id=UUID("00000000-0000-0000-0000-000000000001"),
        file_type=FileType.TXT,
        source_name="analysis.txt",
        version=1,
        blocks=blocks,
        metadata={"encoding": "utf-8"},
    )
