from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from text_verification.domain.documents import DocumentModel, FileType, TextBlock
from text_verification.domain.issues import Issue, IssueSeverity
from text_verification.domain.jobs import JobProgressStage, JobRead, JobStatus


def _block(
    block_id: str,
    text: str,
    start: int,
    end: int,
    *,
    parent_id: str | None = None,
    block_start: int = 0,
    block_end: int | None = None,
) -> TextBlock:
    return TextBlock(
        block_id=block_id,
        kind="paragraph",
        text=text,
        global_start=start,
        global_end=end,
        block_start=block_start,
        block_end=len(text) if block_end is None else block_end,
        page=None,
        paragraph_index=None,
        table_index=None,
        row_index=None,
        cell_index=None,
        bbox=None,
        parent_id=parent_id,
        style={},
        source_locator={},
    )


def _document_with_blocks(text: str, blocks: list[TextBlock]) -> DocumentModel:
    return DocumentModel(
        document_id=uuid4(),
        source_version="sha256:sample",
        file_type=FileType.TXT,
        source_name="sample.txt",
        text=text,
        blocks=blocks,
        parser_name="plain-text",
        parser_version="1",
    )


def test_document_owns_block_local_offsets() -> None:
    block = TextBlock(
        block_id="p-1",
        kind="paragraph",
        text="需要检查的文本",
        global_start=0,
        global_end=7,
        block_start=0,
        block_end=7,
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
    document = DocumentModel(
        document_id=uuid4(),
        source_version="sha256:sample",
        file_type=FileType.DOCX,
        source_name="sample.docx",
        text="需要检查的文本",
        blocks=[block],
        parser_name="docx-parser",
        parser_version="1",
    )

    assert document.blocks[0].text[2:4] == "检查"


def test_document_model_supports_all_source_formats() -> None:
    assert {item.value for item in FileType} == {
        "docx",
        "doc",
        "pdf",
        "txt",
        "rtf",
        "md",
        "csv",
    }


def test_document_model_rejects_block_outside_document_text() -> None:
    with pytest.raises(ValidationError, match="block range"):
        DocumentModel(
            document_id=uuid4(),
            source_version="sha256:abc",
            file_type=FileType.TXT,
            source_name="sample.txt",
            text="abc",
            parser_name="plain-text",
            parser_version="1",
            blocks=[
                TextBlock(
                    block_id="b1",
                    kind="paragraph",
                    text="abcd",
                    global_start=0,
                    global_end=4,
                    block_start=0,
                    block_end=4,
                    page=None,
                    paragraph_index=0,
                    table_index=None,
                    row_index=None,
                    cell_index=None,
                    bbox=None,
                    parent_id=None,
                    style={},
                    source_locator={},
                )
            ],
        )


def test_text_block_rejects_local_range_not_anchored_to_its_text() -> None:
    with pytest.raises(ValidationError, match="local block range"):
        _block("b1", "abc", 0, 3, block_start=1, block_end=4)


def test_document_model_rejects_duplicate_block_ids() -> None:
    with pytest.raises(ValidationError, match="block IDs must be unique"):
        _document_with_blocks(
            "abcdef",
            [
                _block("duplicate", "abc", 0, 3),
                _block("duplicate", "def", 3, 6),
            ],
        )


def test_document_model_rejects_overlap_between_unrelated_blocks() -> None:
    with pytest.raises(ValidationError, match="overlap"):
        _document_with_blocks(
            "abcdef",
            [
                _block("first", "abcd", 0, 4),
                _block("second", "cdef", 2, 6),
            ],
        )


def test_document_model_allows_parent_child_containment() -> None:
    document = _document_with_blocks(
        "abcdef",
        [
            _block("parent", "abcdef", 0, 6),
            _block("child", "bc", 1, 3, parent_id="parent"),
        ],
    )

    assert document.blocks[1].parent_id == "parent"


def test_document_model_allows_grandparent_parent_child_containment() -> None:
    document = _document_with_blocks(
        "abcdefgh",
        [
            _block("grandparent", "abcdefgh", 0, 8),
            _block("parent", "bcdefg", 1, 7, parent_id="grandparent"),
            _block("child", "de", 3, 5, parent_id="parent"),
        ],
    )

    assert [block.parent_id for block in document.blocks] == [
        None,
        "grandparent",
        "parent",
    ]


def test_document_model_rejects_parent_child_overlap_without_containment() -> None:
    with pytest.raises(ValidationError, match="contain"):
        _document_with_blocks(
            "abcdef",
            [
                _block("parent", "abcd", 0, 4),
                _block("child", "cdef", 2, 6, parent_id="parent"),
            ],
        )


def test_document_model_rejects_unknown_parent_block() -> None:
    with pytest.raises(ValidationError, match="parent block"):
        _document_with_blocks(
            "abcdef",
            [_block("child", "abc", 0, 3, parent_id="missing")],
        )


def test_document_model_rejects_parent_cycle() -> None:
    with pytest.raises(ValidationError, match="cycles"):
        _document_with_blocks(
            "abcdef",
            [
                _block("first", "abcdef", 0, 6, parent_id="second"),
                _block("second", "abcdef", 0, 6, parent_id="first"),
            ],
        )


def test_issue_rejects_range_beyond_original_block_contract() -> None:
    with pytest.raises(ValidationError):
        Issue(
            issue_id=uuid4(),
            document_id=uuid4(),
            verification_run_id=uuid4(),
            block_id="p-1",
            page=None,
            start=5,
            end=3,
            block_start=0,
            block_end=2,
            original="错",
            suggestion="正",
            alternatives=[],
            type="typo",
            severity=IssueSeverity.WARNING,
            layer="vocabulary",
            message="错别字",
            description="疑似错别字",
            rule_id="legacy.typo",
            rule_version="2026.08",
            source="legacy",
            source_version="1",
            confidence=0.9,
            auto_fixable=True,
            context="上下文",
        )


def test_issue_supports_canonical_identity_and_review_metadata() -> None:
    verification_run_id = uuid4()
    issue = Issue(
        issue_id=uuid4(),
        document_id=uuid4(),
        verification_run_id=verification_run_id,
        block_id="p-1",
        page=1,
        start=2,
        end=4,
        block_start=0,
        block_end=2,
        original="检查",
        suggestion="核查",
        alternatives=["审查"],
        type="typo",
        severity=IssueSeverity.WARNING,
        layer="vocabulary",
        message="错别字",
        description="建议使用更规范写法",
        rule_id="legacy.typo",
        rule_version="2026.08",
        source="legacy",
        source_version="1",
        confidence=0.9,
        auto_fixable=True,
        context="需要检查的文本",
    )

    assert issue.verification_run_id == verification_run_id
    assert issue.block_start == 0
    assert issue.block_end == 2
    assert issue.review is None
    assert issue.review_reason is None


def test_issue_rejects_original_width_that_differs_from_global_span() -> None:
    with pytest.raises(ValidationError, match="original text length"):
        Issue(
            issue_id=uuid4(),
            document_id=uuid4(),
            verification_run_id=uuid4(),
            block_id=None,
            page=None,
            start=0,
            end=2,
            block_start=None,
            block_end=None,
            original="错",
            suggestion="正",
            alternatives=[],
            type="typo",
            severity=IssueSeverity.WARNING,
            layer="character",
            message="错别字",
            description="疑似错别字",
            rule_id="legacy.typo",
            rule_version="1",
            source="legacy",
            source_version="1",
            confidence=0.9,
            auto_fixable=True,
            context="错字",
        )


def test_issue_rejects_block_span_that_differs_from_global_span() -> None:
    with pytest.raises(ValidationError, match="block range length"):
        Issue(
            issue_id=uuid4(),
            document_id=uuid4(),
            verification_run_id=uuid4(),
            block_id="p-1",
            page=None,
            start=0,
            end=2,
            block_start=0,
            block_end=1,
            original="错字",
            suggestion="正字",
            alternatives=[],
            type="typo",
            severity=IssueSeverity.WARNING,
            layer="character",
            message="错别字",
            description="疑似错别字",
            rule_id="legacy.typo",
            rule_version="1",
            source="legacy",
            source_version="1",
            confidence=0.9,
            auto_fixable=True,
            context="错字",
        )


def test_job_status_contains_all_pipeline_states() -> None:
    assert {status.value for status in JobStatus} == {
        "queued",
        "upload_validated",
        "parsing",
        "checking_format",
        "checking_sensitive",
        "checking_chinese",
        "checking_english",
        "completed",
        "partial",
        "failed",
        "expired",
    }
    assert {"ocr", "exporting", "finalizing"} <= {
        stage.value for stage in JobProgressStage
    }


@pytest.mark.parametrize(
    ("status", "progress", "expected_stage"),
    [
        (JobStatus.PARSING, 25, JobProgressStage.PARSING),
        (JobStatus.PARSING, 40, JobProgressStage.OCR),
        (JobStatus.CHECKING_ENGLISH, 90, JobProgressStage.CHECKING_ENGLISH),
        (JobStatus.CHECKING_ENGLISH, 95, JobProgressStage.FINALIZING),
        (JobStatus.COMPLETED, 100, JobProgressStage.COMPLETED),
    ],
)
def test_job_read_derives_advanced_stage_from_legacy_status_and_progress(
    status: JobStatus,
    progress: int,
    expected_stage: JobProgressStage,
) -> None:
    job = JobRead(
        job_id=uuid4(),
        source_name="sample.pdf",
        file_type=FileType.PDF,
        size_bytes=10,
        status=status,
        progress=progress,
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    assert job.stage is expected_stage


def test_job_read_stage_tracks_status_progress_model_copy_updates() -> None:
    job = JobRead(
        job_id=uuid4(),
        source_name="sample.pdf",
        file_type=FileType.PDF,
        size_bytes=10,
        status=JobStatus.PARSING,
        progress=25,
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    updated = job.model_copy(update={"progress": 40})

    assert updated.stage is JobProgressStage.OCR


def test_job_read_rejects_unsupported_file_type() -> None:
    with pytest.raises(ValidationError):
        JobRead(
            job_id=uuid4(),
            source_name="sample.exe",
            file_type="exe",
            size_bytes=1,
            status=JobStatus.QUEUED,
            progress=0,
            created_at="2026-08-14T00:00:00Z",
            expires_at="2026-08-15T00:00:00Z",
        )


def test_job_read_allows_success_shape_without_error_fields() -> None:
    job = JobRead(
        job_id=uuid4(),
        source_name="sample.docx",
        file_type=FileType.DOCX,
        size_bytes=1,
        status=JobStatus.COMPLETED,
        progress=100,
        created_at="2026-08-14T00:00:00Z",
        expires_at="2026-08-15T00:00:00Z",
    )

    assert job.error_code is None
    assert job.error_message is None
