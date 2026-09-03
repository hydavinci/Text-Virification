from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import UUID

import pytest

from text_verification.application.errors import VerificationError
from text_verification.application.review_revision import ReviewRevisionService
from text_verification.domain.verification import (
    DocumentRevisionKind,
    PersistedDocumentRevision,
    ReviewRevisionDraft,
)

JOB_ID = UUID("10000000-0000-4000-8000-000000000001")
DOCUMENT_ID = UUID("20000000-0000-4000-8000-000000000002")
RUN_ID = UUID("30000000-0000-4000-8000-000000000003")
REVISION_ID = UUID("40000000-0000-4000-8000-000000000004")
CREATED_AT = datetime(2026, 9, 3, 4, 0, tzinfo=UTC)


class RecordingRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, ReviewRevisionDraft, datetime]] = []
        self.commit_calls = 0
        self.rollback_calls = 0
        self.error: Exception | None = None

    def persist_review_revision(
        self,
        job_id: UUID,
        draft: ReviewRevisionDraft,
        *,
        created_at: datetime,
    ) -> PersistedDocumentRevision:
        self.calls.append((job_id, draft, created_at))
        if self.error is not None:
            raise self.error
        return PersistedDocumentRevision(
            revision_id=draft.revision_id,
            document_id=draft.document_id,
            verification_run_id=draft.verification_run_id,
            source_version=draft.source_version,
            revision_number=1,
            created_at=created_at,
            parent_revision_id=draft.parent_revision_id,
            persistence_state="persisted",
            kind=draft.kind,
            text=draft.text,
        )

    def commit(self) -> None:
        self.commit_calls += 1

    def rollback(self) -> None:
        self.rollback_calls += 1


def draft() -> ReviewRevisionDraft:
    return ReviewRevisionDraft(
        revision_id=REVISION_ID,
        document_id=DOCUMENT_ID,
        verification_run_id=RUN_ID,
        source_version="sha256:source",
        parent_revision_id=None,
        kind=DocumentRevisionKind.REVIEW,
        text="修订文本",
    )


def service(repository: RecordingRepository) -> ReviewRevisionService:
    @contextmanager
    def factory() -> Iterator[RecordingRepository]:
        yield repository

    return ReviewRevisionService(factory, now_factory=lambda: CREATED_AT)


def test_persists_browser_revision_identity_and_commits_once() -> None:
    repository = RecordingRepository()

    persisted = service(repository).persist(JOB_ID, draft())

    assert persisted.revision_number == 1
    assert persisted.persistence_state == "persisted"
    assert repository.calls == [(JOB_ID, draft(), CREATED_AT)]
    assert repository.commit_calls == 1
    assert repository.rollback_calls == 0


@pytest.mark.parametrize(
    ("error", "code", "retryable"),
    [
        (LookupError("missing"), "revision_identity_not_found", False),
        (ValueError("stale"), "revision_conflict", False),
        (RuntimeError("database unavailable"), "revision_persistence_failed", True),
    ],
)
def test_rolls_back_and_maps_repository_failures(
    error: Exception,
    code: str,
    retryable: bool,
) -> None:
    repository = RecordingRepository()
    repository.error = error

    with pytest.raises(VerificationError) as raised:
        service(repository).persist(JOB_ID, draft())

    assert raised.value.code == code
    assert raised.value.stage == "revision_persistence"
    assert raised.value.retryable is retryable
    assert repository.commit_calls == 0
    assert repository.rollback_calls == 1
