from uuid import uuid4

import pytest
from pydantic import ValidationError

from text_verification.domain.documents import DocumentModel, FileType, TextBlock
from text_verification.domain.issues import Issue, IssueSeverity
from text_verification.domain.jobs import JobRead, JobStatus


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
