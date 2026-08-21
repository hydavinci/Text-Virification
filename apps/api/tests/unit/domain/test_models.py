from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from text_verification.domain.documents import DocumentModel, FileType, TextBlock
from text_verification.domain.issues import DecisionAction, DecisionCommand, Issue, IssueSeverity
from text_verification.domain.jobs import JobRead, JobStatus
from text_verification.domain.revisions import (
    DocumentVersionRead,
    DocumentVersionStatus,
    DraftBlock,
    EditDraftRead,
)

NOW = datetime(2026, 8, 21, 0, 0, tzinfo=UTC)


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
        version=1,
        blocks=[block],
        metadata={},
    )

    assert document.blocks[0].text[2:4] == "检查"


def test_document_model_requires_positive_version() -> None:
    with pytest.raises(ValidationError):
        DocumentModel(
            document_id=uuid4(),
            file_type=FileType.TXT,
            source_name="sample.txt",
            version=0,
            blocks=[],
            metadata={},
        )


def test_text_block_rejects_empty_block_id() -> None:
    with pytest.raises(ValidationError):
        TextBlock(
            block_id="",
            kind="paragraph",
            text="正文",
            page=None,
            paragraph_index=0,
            parent_id=None,
            style={},
            source_locator={},
        )


def test_accepted_decision_requires_final_replacement() -> None:
    with pytest.raises(ValidationError):
        DecisionCommand(
            issue_id=uuid4(),
            issue_version=1,
            expected_revision=0,
            action=DecisionAction.ACCEPTED,
            replacement=None,
            suggestion_id=None,
        )


def test_ignored_decision_rejects_replacement_and_suggestion_id() -> None:
    with pytest.raises(ValidationError):
        DecisionCommand(
            issue_id=uuid4(),
            issue_version=1,
            expected_revision=0,
            action=DecisionAction.IGNORED,
            replacement="保留",
            suggestion_id=uuid4(),
        )


def test_draft_rejects_duplicate_block_ids() -> None:
    block = DraftBlock(block_id="p-1", text="正文")
    with pytest.raises(ValidationError):
        EditDraftRead(
            draft_id=uuid4(),
            job_id=uuid4(),
            base_version_id=uuid4(),
            revision=1,
            blocks=[block, block],
            created_at=NOW,
            updated_at=NOW,
        )


def test_failed_version_requires_failure_fields() -> None:
    with pytest.raises(ValidationError):
        DocumentVersionRead(
            version_id=uuid4(),
            job_id=uuid4(),
            parent_version_id=None,
            revision_number=1,
            status=DocumentVersionStatus.FAILED,
            source_kind="upload",
            created_reason="initial_upload",
            content_sha256=None,
            created_at=NOW,
            started_at=NOW,
            completed_at=NOW,
            failure_code=None,
            failure_message=None,
        )


def test_succeeded_version_rejects_failure_fields() -> None:
    with pytest.raises(ValidationError):
        DocumentVersionRead(
            version_id=uuid4(),
            job_id=uuid4(),
            parent_version_id=None,
            revision_number=1,
            status=DocumentVersionStatus.SUCCEEDED,
            source_kind="upload",
            created_reason="initial_upload",
            content_sha256="sha256",
            created_at=NOW,
            started_at=NOW,
            completed_at=NOW,
            failure_code="analysis_failed",
            failure_message="失败",
        )


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
