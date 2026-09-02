from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest

from text_verification.application.verification_pipeline import (
    VerificationCommand,
    VerificationPipeline,
)
from text_verification.checkers.registry import CheckerRegistry
from text_verification.document_processing.errors import (
    OcrProcessingError,
)
from text_verification.document_processing.ocr_provider import OcrTextBox
from text_verification.document_processing.pdf_models import PdfResourceLimits
from text_verification.domain.documents import DocumentModel, FileType, TextBlock
from text_verification.domain.ports import (
    CheckContext,
    CheckResult,
    VerificationProgressObserver,
    VerificationProgressStage,
)
from text_verification.domain.verification import (
    VerificationExecutionMode,
    VerificationOptions,
)
from text_verification.parsers.errors import PdfResourceLimitError
from text_verification.parsers.pdf_parser import PdfParser
from text_verification.parsers.registry import ParserRegistry


@dataclass
class ProgressParser:
    operations: list[str]
    supported_type: FileType = FileType.TXT

    def parse(self, source_path: Path) -> DocumentModel:
        self.operations.append("parse")
        return _document(source_path.name)


@dataclass
class ProgressChecker:
    operations: list[str]
    name: str = "progress"
    version: str = "1"
    supported_languages: set[str] | None = None

    def check(
        self,
        document: DocumentModel,
        context: CheckContext,
        *,
        progress_observer: VerificationProgressObserver | None = None,
    ) -> CheckResult:
        del document, context
        self.operations.append("check")
        assert progress_observer is not None
        progress_observer(VerificationProgressStage.CHECKING_FORMAT)
        return CheckResult(())


def test_pipeline_emits_parsing_before_parser_and_passes_observer_to_checker(
    tmp_path: Path,
) -> None:
    operations: list[str] = []
    source_path = tmp_path / "source.txt"
    source_path.write_text("clean", encoding="utf-8")
    pipeline = VerificationPipeline(
        parsers=ParserRegistry([ProgressParser(operations)]),
        checkers=CheckerRegistry([ProgressChecker(operations)]),
        reviewer=None,
    )

    pipeline.run(
        VerificationCommand(
            document_id=uuid4(),
            source_path=source_path,
            direct_text=None,
            source_name="source.txt",
            file_type=FileType.TXT,
            options=VerificationOptions(),
            execution_mode=VerificationExecutionMode.ASYNCHRONOUS,
        ),
        progress_observer=lambda stage: operations.append(f"stage:{stage.value}"),
    )

    assert operations == [
        "stage:parsing",
        "parse",
        "check",
        "stage:checking_format",
    ]


class _FakeOcr:
    def recognize(self, image: object, language: str) -> list[OcrTextBox]:
        del image, language
        return [
            OcrTextBox(
                text="test@example.com",
                confidence=0.99,
                bbox=((40.0, 40.0), (300.0, 40.0), (300.0, 80.0), (40.0, 80.0)),
            )
        ]


def test_pdf_parser_emits_ocr_only_when_a_page_enters_ocr_work() -> None:
    fixtures = Path(__file__).resolve().parents[2] / "fixtures" / "pdf"
    parser = PdfParser(ocr=_FakeOcr())
    text_stages: list[VerificationProgressStage] = []
    scan_stages: list[VerificationProgressStage] = []

    parser.parse_with_progress(
        fixtures / "text-page.pdf",
        progress_observer=text_stages.append,
    )
    parser.parse_with_progress(
        fixtures / "scanned-page.pdf",
        progress_observer=scan_stages.append,
    )

    assert VerificationProgressStage.OCR not in text_stages
    assert scan_stages == [VerificationProgressStage.OCR]


def test_pdf_parser_emits_ocr_after_successful_render_and_before_recognize(
    monkeypatch,
) -> None:
    from text_verification.parsers import pdf_parser as pdf_parser_module

    fixtures = Path(__file__).resolve().parents[2] / "fixtures" / "pdf"
    operations: list[str] = []
    original_render = pdf_parser_module._render_page_for_ocr

    def render(page, limits):
        rendered = original_render(page, limits)
        operations.append("rendered")
        return rendered

    class OrderingOcr:
        def recognize(self, image: object, language: str) -> list[OcrTextBox]:
            del image, language
            operations.append("recognize")
            assert operations == ["rendered", "stage:ocr", "recognize"]
            return _FakeOcr().recognize(object(), "zh")

    monkeypatch.setattr(pdf_parser_module, "_render_page_for_ocr", render)

    PdfParser(ocr=OrderingOcr()).parse_with_progress(
        fixtures / "scanned-page.pdf",
        progress_observer=lambda stage: operations.append(f"stage:{stage.value}"),
    )

    assert operations == ["rendered", "stage:ocr", "recognize"]


def test_pdf_raster_resource_failure_emits_no_ocr_stage() -> None:
    fixtures = Path(__file__).resolve().parents[2] / "fixtures" / "pdf"
    stages: list[VerificationProgressStage] = []

    with pytest.raises(PdfResourceLimitError):
        PdfParser(
            ocr=_FakeOcr(),
            limits=PdfResourceLimits(max_ocr_raster_width=1),
        ).parse_with_progress(
            fixtures / "scanned-page.pdf",
            progress_observer=stages.append,
        )

    assert stages == []


@pytest.mark.parametrize(
    ("error", "expected_type"),
    [
        (RuntimeError("render failed"), OcrProcessingError),
        (ValueError("invalid page"), OcrProcessingError),
        (OSError("renderer unavailable"), OcrProcessingError),
        (MemoryError("allocation failed"), OcrProcessingError),
    ],
)
def test_get_pixmap_failure_emits_no_ocr_stage(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected_type: type[Exception],
) -> None:
    import pymupdf

    fixtures = Path(__file__).resolve().parents[2] / "fixtures" / "pdf"
    stages: list[VerificationProgressStage] = []

    def fail_render(page: pymupdf.Page, **kwargs: object) -> object:
        del page, kwargs
        raise error

    monkeypatch.setattr(pymupdf.Page, "get_pixmap", fail_render)

    with pytest.raises(expected_type):
        PdfParser(ocr=_FakeOcr()).parse_with_progress(
            fixtures / "scanned-page.pdf",
            progress_observer=stages.append,
        )

    assert stages == []


def test_pixmap_encoding_failure_emits_no_ocr_stage_and_closes_pixmap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pymupdf

    class FailingPixmap:
        width = 20
        height = 20
        stride = 60

        def __init__(self) -> None:
            self.closed = False

        def tobytes(self, output: str) -> bytes:
            assert output == "png"
            raise RuntimeError("encode failed")

        def close(self) -> None:
            self.closed = True

    fixtures = Path(__file__).resolve().parents[2] / "fixtures" / "pdf"
    stages: list[VerificationProgressStage] = []
    pixmap = FailingPixmap()
    monkeypatch.setattr(
        pymupdf.Page,
        "get_pixmap",
        lambda page, **kwargs: pixmap,
    )

    with pytest.raises(OcrProcessingError) as raised:
        PdfParser(ocr=_FakeOcr()).parse_with_progress(
            fixtures / "scanned-page.pdf",
            progress_observer=stages.append,
        )

    assert stages == []
    assert raised.value.code == "ocr_render_encoding_failed"
    assert raised.value.retryable is True
    assert pixmap.closed is True


def _document(source_name: str) -> DocumentModel:
    return DocumentModel(
        document_id=uuid4(),
        source_version="sha256:progress",
        file_type=FileType.TXT,
        source_name=source_name,
        text="clean",
        blocks=[
            TextBlock(
                block_id="p-0",
                kind="paragraph",
                text="clean",
                global_start=0,
                global_end=5,
                block_start=0,
                block_end=5,
                page=None,
                paragraph_index=0,
                table_index=None,
                row_index=None,
                cell_index=None,
                bbox=None,
                parent_id=None,
                style={},
                source_locator={"paragraph_index": 0},
            )
        ],
        parser_name="progress",
        parser_version="1",
    )
