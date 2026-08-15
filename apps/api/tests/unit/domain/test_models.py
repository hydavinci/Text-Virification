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
        page=None,
        paragraph_index=0,
        parent_id=None,
        style={},
        source_locator={"paragraph_index": 0},
    )
    document = DocumentModel(
        document_id=uuid4(),
        file_type=FileType.DOCX,
        source_name="sample.docx",
        blocks=[block],
    )

    assert document.blocks[0].text[2:4] == "检查"


def test_issue_rejects_range_beyond_original_block_contract() -> None:
    with pytest.raises(ValidationError):
        Issue(
            issue_id=uuid4(),
            document_id=uuid4(),
            block_id="p-1",
            page=None,
            start=5,
            end=3,
            original="错",
            suggestion="正",
            alternatives=[],
            type="typo",
            severity=IssueSeverity.WARNING,
            layer="vocabulary",
            message="错别字",
            rule_id="legacy.typo",
            source="legacy",
            source_version="1",
            confidence=0.9,
            auto_fixable=True,
            context="上下文",
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
