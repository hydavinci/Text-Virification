from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from text_verification.checkers.models import CheckCategory
from text_verification.domain.documents import DocumentModel, FileType, TextBlock
from text_verification.domain.issues import Issue, IssueSeverity
from text_verification.domain.revisions import DocumentVersionStatus
from text_verification.infrastructure.analysis_repositories import AnalysisRepository
from text_verification.infrastructure.repositories import JobRepository
from text_verification.infrastructure.revision_repository import (
    ImmutableDocumentVersionError,
    RevisionRepository,
)


@dataclass(frozen=True)
class SeededJob:
    job_id: UUID
    document_v1: DocumentModel
    document_v2: DocumentModel


@pytest.fixture
def seeded_job(db_session: Session) -> SeededJob:
    return SeededJob(
        job_id=_seed_job(db_session),
        document_v1=_build_document(version=1, text="第一版"),
        document_v2=_build_document(version=2, text="第二版"),
    )


def test_complete_analysis_activates_new_version_without_deleting_parent(
    db_session: Session,
    seeded_job: SeededJob,
) -> None:
    revisions = RevisionRepository(db_session)
    analysis = AnalysisRepository(db_session)
    first = revisions.create_queued_version(
        seeded_job.job_id,
        parent_version_id=None,
        reason="upload",
        idempotency_key=None,
    )
    revisions.complete_analysis(first.version_id, seeded_job.document_v1, [], {})
    second = revisions.create_queued_version(
        seeded_job.job_id,
        first.version_id,
        reason="edited",
        idempotency_key="edit-1",
    )
    revisions.complete_analysis(second.version_id, seeded_job.document_v2, [], {})
    db_session.commit()

    active = revisions.get_active_version(seeded_job.job_id)

    assert active is not None
    assert active.version_id == second.version_id
    assert analysis.get_document(seeded_job.job_id, first.version_id) == seeded_job.document_v1
    assert analysis.get_document(seeded_job.job_id, second.version_id) == seeded_job.document_v2


def test_complete_analysis_rejects_succeeded_version_as_immutable(
    db_session: Session,
    seeded_job: SeededJob,
) -> None:
    revisions = RevisionRepository(db_session)
    version = revisions.create_queued_version(
        seeded_job.job_id,
        parent_version_id=None,
        reason="upload",
        idempotency_key=None,
    )
    revisions.complete_analysis(version.version_id, seeded_job.document_v1, [], {})
    db_session.commit()

    with pytest.raises(ImmutableDocumentVersionError):
        revisions.complete_analysis(version.version_id, seeded_job.document_v2, [], {})


def test_failed_version_never_becomes_active(
    db_session: Session,
    seeded_job: SeededJob,
) -> None:
    revisions = RevisionRepository(db_session)
    first = revisions.create_queued_version(
        seeded_job.job_id,
        parent_version_id=None,
        reason="upload",
        idempotency_key=None,
    )
    revisions.complete_analysis(first.version_id, seeded_job.document_v1, [], {})
    failed = revisions.create_queued_version(
        seeded_job.job_id,
        first.version_id,
        reason="edited",
        idempotency_key="edit-1",
    )
    revisions.mark_analyzing(failed.version_id)
    failed_read = revisions.fail_version(
        failed.version_id,
        code="checker_failed",
        message="分析失败。",
    )
    db_session.commit()

    active = revisions.get_active_version(seeded_job.job_id)
    versions = revisions.list_versions(seeded_job.job_id)

    assert failed_read.status == DocumentVersionStatus.FAILED
    assert active is not None
    assert active.version_id == first.version_id
    assert [version.version_id for version in versions] == [first.version_id, failed.version_id]
    assert [version.status for version in versions] == [
        DocumentVersionStatus.SUCCEEDED,
        DocumentVersionStatus.FAILED,
    ]


def _seed_job(db_session: Session) -> UUID:
    now = datetime.now(UTC)
    job_id = uuid4()
    repository = JobRepository(db_session)
    repository.create_job(
        job_id=job_id,
        source_name="analysis.txt",
        file_type=FileType.TXT.value,
        size_bytes=16,
        storage_key=str(job_id),
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )
    repository.commit()
    return job_id


def _build_document(*, version: int, text: str) -> DocumentModel:
    return DocumentModel(
        document_id=UUID("00000000-0000-0000-0000-000000000001"),
        file_type=FileType.TXT,
        source_name="analysis.txt",
        version=version,
        blocks=[
            TextBlock(
                block_id="p-000001",
                kind="paragraph",
                text=text,
                page=1,
                paragraph_index=0,
                parent_id=None,
                style={"style_name": "Normal"},
                source_locator={"paragraph_index": 0},
            )
        ],
        metadata={"language": "zh-CN"},
    )


def _build_issue(document: DocumentModel) -> Issue:
    return Issue(
        issue_id=uuid4(),
        document_id=document.document_id,
        document_version=document.version,
        block_id="p-000001",
        page=1,
        start=0,
        end=len(document.blocks[0].text),
        original=document.blocks[0].text,
        suggestion=document.blocks[0].text,
        alternatives=[document.blocks[0].text],
        type="literal",
        severity=IssueSeverity.WARNING,
        layer=CheckCategory.SECURITY.value,
        message="命中规则。",
        rule_id="security-001",
        source="test",
        source_version="1",
        confidence=1.0,
        auto_fixable=True,
        context=document.blocks[0].text,
    )
