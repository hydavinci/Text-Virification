from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi import FastAPI

from text_verification.application.errors import VerificationError
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


def payload() -> dict[str, object]:
    return {
        "revision_id": str(REVISION_ID),
        "document_id": str(DOCUMENT_ID),
        "verification_run_id": str(RUN_ID),
        "source_version": "sha256:source",
        "parent_revision_id": None,
        "kind": "review",
        "text": "修订文本",
    }


def persisted() -> PersistedDocumentRevision:
    return PersistedDocumentRevision(
        revision_id=REVISION_ID,
        document_id=DOCUMENT_ID,
        verification_run_id=RUN_ID,
        source_version="sha256:source",
        revision_number=1,
        created_at=CREATED_AT,
        parent_revision_id=None,
        persistence_state="persisted",
        kind=DocumentRevisionKind.REVIEW,
        text="修订文本",
    )


def test_revision_route_persists_browser_uuid_without_accepting_a_number(
    client,
    app: FastAPI,
) -> None:
    from text_verification.api.dependencies import get_review_revision_service

    calls: list[tuple[UUID, ReviewRevisionDraft]] = []

    class FakeService:
        def persist(
            self,
            job_id: UUID,
            draft: ReviewRevisionDraft,
        ) -> PersistedDocumentRevision:
            calls.append((job_id, draft))
            return persisted()

    app.dependency_overrides[get_review_revision_service] = FakeService

    response = client.post(f"/api/v1/jobs/{JOB_ID}/revisions", json=payload())

    assert response.status_code == 200
    assert response.json() == persisted().model_dump(mode="json")
    assert calls == [
        (
            JOB_ID,
            ReviewRevisionDraft.model_validate(payload()),
        )
    ]

    numbered_payload = {**payload(), "revision_number": 9}
    invalid = client.post(
        f"/api/v1/jobs/{JOB_ID}/revisions",
        json=numbered_payload,
    )
    assert invalid.status_code == 422

    self_parent = client.post(
        f"/api/v1/jobs/{JOB_ID}/revisions",
        json={**payload(), "parent_revision_id": str(REVISION_ID)},
    )
    assert self_parent.status_code == 422

    source_sentinel = client.post(
        f"/api/v1/jobs/{JOB_ID}/revisions",
        json={**payload(), "kind": "source"},
    )
    assert source_sentinel.status_code == 422


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (
            VerificationError(
                "revision_identity_not_found",
                "revision_persistence",
                "not found",
                False,
            ),
            404,
            "revision_identity_not_found",
        ),
        (
            VerificationError(
                "revision_conflict",
                "revision_persistence",
                "conflict",
                False,
            ),
            409,
            "revision_conflict",
        ),
        (
            VerificationError(
                "revision_persistence_failed",
                "revision_persistence",
                "unavailable",
                True,
            ),
            503,
            "revision_persistence_failed",
        ),
        (
            VerificationError(
                "revision_text_too_large",
                "revision_persistence",
                "too large",
                False,
            ),
            413,
            "revision_text_too_large",
        ),
    ],
)
def test_revision_route_maps_typed_service_failures(
    client,
    app: FastAPI,
    error: VerificationError,
    status_code: int,
    code: str,
) -> None:
    from text_verification.api.dependencies import get_review_revision_service

    class FakeService:
        def persist(self, job_id: UUID, draft: ReviewRevisionDraft) -> None:
            del job_id, draft
            raise error

    app.dependency_overrides[get_review_revision_service] = FakeService

    response = client.post(f"/api/v1/jobs/{JOB_ID}/revisions", json=payload())

    assert response.status_code == status_code
    assert response.json()["detail"] == {
        "code": code,
        "stage": "revision_persistence",
        "message": error.message,
        "retryable": error.retryable,
    }
