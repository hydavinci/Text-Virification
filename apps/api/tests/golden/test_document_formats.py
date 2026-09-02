from __future__ import annotations

import io
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import pymupdf
import pytest
from docx import Document

from text_verification.application.factory import build_default_verification_pipeline
from text_verification.application.verification_pipeline import VerificationCommand
from text_verification.config import Settings
from text_verification.domain.documents import FileType
from text_verification.domain.verification import (
    VerificationExecutionMode,
    VerificationOptions,
)
from text_verification.infrastructure.storage import JobStorage

SAMPLE_TEXT = "Contact test@example.com for review."


def _txt(target: Path) -> bytes:
    del target
    return SAMPLE_TEXT.encode("utf-8")


def _markdown(target: Path) -> bytes:
    del target
    return f"# Review\n\n{SAMPLE_TEXT}".encode()


def _csv(target: Path) -> bytes:
    del target
    return f"kind,value\ncontact,{SAMPLE_TEXT}\n".encode()


def _rtf(target: Path) -> bytes:
    del target
    return ("{\\rtf1\\ansi " + SAMPLE_TEXT + "}").encode("ascii")


def _docx(target: Path) -> bytes:
    stream = io.BytesIO()
    document = Document()
    document.add_heading("Review", level=1)
    document.add_paragraph(SAMPLE_TEXT)
    document.save(stream)
    return stream.getvalue()


def _pdf(target: Path) -> bytes:
    document = pymupdf.open()
    try:
        page = document.new_page(width=500, height=200)
        page.insert_text((40, 80), SAMPLE_TEXT, fontsize=14, fontname="helv")
        return document.tobytes()
    finally:
        document.close()


FORMAT_BUILDERS: dict[FileType, Callable[[Path], bytes]] = {
    FileType.TXT: _txt,
    FileType.DOCX: _docx,
    FileType.PDF: _pdf,
    FileType.RTF: _rtf,
    FileType.MARKDOWN: _markdown,
    FileType.CSV: _csv,
}


@pytest.mark.parametrize("file_type", list(FileType))
def test_async_storage_accepts_all_seven_formats(
    tmp_path: Path,
    file_type: FileType,
) -> None:
    storage = JobStorage(tmp_path, max_upload_bytes=5 * 1024 * 1024)
    if file_type is FileType.DOC:
        payload = bytes.fromhex("D0CF11E0A1B11AE1") + b"\x00" * 16
    else:
        payload = FORMAT_BUILDERS[file_type](tmp_path / f"fixture.{file_type.value}")

    stored = storage.save_bytes(uuid4(), f"fixture.{file_type.value}", payload)

    assert stored.file_type is file_type


@pytest.mark.parametrize("file_type", list(FORMAT_BUILDERS))
def test_six_self_contained_golden_formats_produce_equivalent_issue_semantics(
    tmp_path: Path,
    file_type: FileType,
) -> None:
    source = tmp_path / f"fixture.{file_type.value}"
    source.write_bytes(FORMAT_BUILDERS[file_type](source))
    pipeline = build_default_verification_pipeline(Settings(llm_api_key=""))

    result = pipeline.run(
        VerificationCommand(
            document_id=uuid4(),
            source_path=source,
            direct_text=None,
            source_name=source.name,
            file_type=file_type,
            options=VerificationOptions(),
            execution_mode=VerificationExecutionMode.ASYNCHRONOUS,
        )
    )

    issue = next(issue for issue in result.issues if issue.type == "pii_email")
    assert SAMPLE_TEXT in result.text
    assert issue.original == "test@example.com"
    assert result.text[issue.start : issue.end] == issue.original
    assert issue.block_id is not None
    assert result.execution_mode is VerificationExecutionMode.ASYNCHRONOUS
    assert result.source_version.startswith("sha256:")


def test_legacy_doc_golden_is_explicitly_converter_limited(tmp_path: Path) -> None:
    converter = shutil.which("textutil")
    if converter is None:
        pytest.skip(
            "Legacy DOC golden parsing requires the optional textutil converter; "
            "upload acceptance remains covered without it."
        )
    rtf_source = tmp_path / "legacy-source.rtf"
    rtf_source.write_bytes(_rtf(rtf_source))
    subprocess.run(
        [converter, "-convert", "doc", str(rtf_source), "-output", str(tmp_path / "legacy.doc")],
        check=True,
        capture_output=True,
        timeout=30,
    )
    source = tmp_path / "legacy.doc"
    pipeline = build_default_verification_pipeline(Settings(llm_api_key=""))

    result = pipeline.run(
        VerificationCommand(
            document_id=uuid4(),
            source_path=source,
            direct_text=None,
            source_name=source.name,
            file_type=FileType.DOC,
            options=VerificationOptions(),
            execution_mode=VerificationExecutionMode.ASYNCHRONOUS,
        )
    )

    assert SAMPLE_TEXT in result.text
    assert any(issue.type == "pii_email" for issue in result.issues)
