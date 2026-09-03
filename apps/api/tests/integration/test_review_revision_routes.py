import json
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi import FastAPI

from text_verification.application.errors import VerificationError
from text_verification.domain.verification import (
    DocumentRevisionKind,
    PersistedDocumentRevision,
    ReviewRevisionSubmission,
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
        "base_result": {
            "document_id": str(DOCUMENT_ID),
            "verification_run_id": str(RUN_ID),
            "source_version": "sha256:source",
        },
    }


def bound_payload() -> dict[str, object]:
    return payload()


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

    calls: list[tuple[UUID, ReviewRevisionSubmission]] = []

    class FakeService:
        def persist(
            self,
            job_id: UUID,
            submission: ReviewRevisionSubmission,
        ) -> PersistedDocumentRevision:
            calls.append((job_id, submission))
            return persisted()

    app.dependency_overrides[get_review_revision_service] = FakeService

    response = client.post(f"/api/v1/jobs/{JOB_ID}/revisions", json=payload())

    assert response.status_code == 200
    assert response.json() == persisted().model_dump(mode="json")
    assert calls == [
        (
            JOB_ID,
            ReviewRevisionSubmission.model_validate(payload()),
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


def test_revision_route_forwards_opaque_recheck_provenance(
    client,
    app: FastAPI,
) -> None:
    from text_verification.api.dependencies import get_review_revision_service

    calls: list[tuple[UUID, ReviewRevisionSubmission]] = []
    provenance_payload = {
        "grant": "opaque.server.grant",
        "result_document_id": "50000000-0000-4000-8000-000000000005",
        "result_verification_run_id": "60000000-0000-4000-8000-000000000006",
        "result_source_version": "sha256:" + "b" * 64,
    }

    class FakeService:
        def persist(
            self,
            job_id: UUID,
            submission: ReviewRevisionSubmission,
        ) -> PersistedDocumentRevision:
            assert submission.recheck_provenance is not None
            calls.append((job_id, submission))
            return persisted()

    app.dependency_overrides[get_review_revision_service] = FakeService

    response = client.post(
        f"/api/v1/jobs/{JOB_ID}/revisions",
        json={
            **payload(),
            "base_result": {
                "document_id": provenance_payload["result_document_id"],
                "verification_run_id": provenance_payload[
                    "result_verification_run_id"
                ],
                "source_version": provenance_payload["result_source_version"],
            },
            "recheck_provenance": provenance_payload,
        },
    )

    assert response.status_code == 200
    assert calls == [
        (
            JOB_ID,
            ReviewRevisionSubmission.model_validate(
                {
                    **payload(),
                    "base_result": {
                        "document_id": provenance_payload[
                            "result_document_id"
                        ],
                        "verification_run_id": provenance_payload[
                            "result_verification_run_id"
                        ],
                        "source_version": provenance_payload[
                            "result_source_version"
                        ],
                    },
                    "recheck_provenance": provenance_payload,
                }
            ),
        )
    ]


def test_revision_recheck_payload_uses_revision_text_without_duplication(
    client,
    app: FastAPI,
) -> None:
    from text_verification.api.dependencies import get_review_revision_service

    fresh_document_id = "50000000-0000-4000-8000-000000000005"
    fresh_run_id = "60000000-0000-4000-8000-000000000006"
    fresh_source_version = "sha256:" + "b" * 64

    class FakeService:
        def persist(
            self,
            job_id: UUID,
            submission: ReviewRevisionSubmission,
        ) -> PersistedDocumentRevision:
            del job_id
            assert submission.recheck_provenance is not None
            return persisted()

    app.dependency_overrides[get_review_revision_service] = FakeService

    response = client.post(
        f"/api/v1/jobs/{JOB_ID}/revisions",
        json={
            **payload(),
            "kind": "manual",
            "base_result": {
                "document_id": fresh_document_id,
                "verification_run_id": fresh_run_id,
                "source_version": fresh_source_version,
            },
            "recheck_provenance": {
                "grant": "opaque.server.grant",
                "result_document_id": fresh_document_id,
                "result_verification_run_id": fresh_run_id,
                "result_source_version": fresh_source_version,
            },
        },
    )

    assert response.status_code == 200


def test_revision_route_requires_explicit_base_result_binding(
    client,
    app: FastAPI,
) -> None:
    from text_verification.api.dependencies import get_review_revision_service

    class FakeService:
        def persist(
            self,
            job_id: UUID,
            submission: ReviewRevisionSubmission,
        ) -> PersistedDocumentRevision:
            del job_id, submission
            return persisted()

    app.dependency_overrides[get_review_revision_service] = FakeService

    unbound = dict(payload())
    del unbound["base_result"]
    response = client.post(f"/api/v1/jobs/{JOB_ID}/revisions", json=unbound)

    assert response.status_code == 422


def test_revision_json_body_limit_is_inclusive_and_checked_before_parsing(
    client,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from text_verification.api.dependencies import get_review_revision_service
    from text_verification.api.routes import jobs as jobs_routes

    body = json.dumps(bound_payload(), separators=(",", ":")).encode()

    class FakeService:
        def persist(self, *args: object, **kwargs: object) -> PersistedDocumentRevision:
            del args, kwargs
            return persisted()

    app.dependency_overrides[get_review_revision_service] = FakeService
    monkeypatch.setattr(
        jobs_routes,
        "max_revision_request_body_bytes",
        lambda _max_upload_bytes: len(body),
        raising=False,
    )

    accepted = client.post(
        f"/api/v1/jobs/{JOB_ID}/revisions",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    monkeypatch.setattr(
        jobs_routes,
        "max_revision_request_body_bytes",
        lambda _max_upload_bytes: len(body) - 1,
        raising=False,
    )
    rejected = client.post(
        f"/api/v1/jobs/{JOB_ID}/revisions",
        content=body,
        headers={"Content-Type": "application/json"},
    )

    assert accepted.status_code != 413
    assert rejected.status_code == 413


def test_revision_json_body_limit_rejects_chunked_body_without_content_length(
    client,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from text_verification.api.dependencies import get_review_revision_service
    from text_verification.api.routes import jobs as jobs_routes

    body = json.dumps(bound_payload(), separators=(",", ":")).encode()

    class FakeService:
        def persist(self, *args: object, **kwargs: object) -> PersistedDocumentRevision:
            del args, kwargs
            return persisted()

    app.dependency_overrides[get_review_revision_service] = FakeService
    monkeypatch.setattr(
        jobs_routes,
        "max_revision_request_body_bytes",
        lambda _max_upload_bytes: len(body) - 1,
        raising=False,
    )

    response = client.post(
        f"/api/v1/jobs/{JOB_ID}/revisions",
        content=iter((body[:17], body[17:])),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413


def test_revision_body_limit_allows_worst_case_escaped_revision_text(
    client,
    app: FastAPI,
    tmp_path,
) -> None:
    from text_verification.api.dependencies import get_review_revision_service
    from text_verification.config import Settings, get_settings

    text = "\0" * 11_000
    fresh_document_id = "50000000-0000-4000-8000-000000000005"
    fresh_run_id = "60000000-0000-4000-8000-000000000006"
    fresh_source_version = "sha256:" + "b" * 64
    request_payload = {
        **payload(),
        "kind": "manual",
        "text": text,
        "base_result": {
            "document_id": fresh_document_id,
            "verification_run_id": fresh_run_id,
            "source_version": fresh_source_version,
        },
        "recheck_provenance": {
            "grant": "opaque-server-grant",
            "result_document_id": fresh_document_id,
            "result_verification_run_id": fresh_run_id,
            "result_source_version": fresh_source_version,
        },
    }
    body = json.dumps(request_payload).encode()

    class FakeService:
        def persist(self, *args: object, **kwargs: object) -> PersistedDocumentRevision:
            del args, kwargs
            return persisted()

    app.dependency_overrides[get_settings] = lambda: Settings(
        app_env="test",
        storage_root=tmp_path,
        max_upload_bytes=len(text),
    )
    app.dependency_overrides[get_review_revision_service] = FakeService

    response = client.post(
        f"/api/v1/jobs/{JOB_ID}/revisions",
        content=body,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 200


def test_revision_json_reader_does_not_buffer_the_complete_raw_body(
    client,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from text_verification.api import body_readers
    from text_verification.api.dependencies import get_review_revision_service

    calls = 0
    original = body_readers.read_bounded_body

    async def recording_reader(*args: object, **kwargs: object) -> bytes:
        nonlocal calls
        calls += 1
        return await original(*args, **kwargs)

    class FakeService:
        def persist(self, *args: object, **kwargs: object) -> PersistedDocumentRevision:
            del args, kwargs
            return persisted()

    monkeypatch.setattr(body_readers, "read_bounded_body", recording_reader)
    app.dependency_overrides[get_review_revision_service] = FakeService

    response = client.post(
        f"/api/v1/jobs/{JOB_ID}/revisions",
        json=payload(),
    )

    assert response.status_code == 200
    assert calls == 0


def test_revision_json_errors_never_reflect_grants_or_text(
    client,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "revision-grant-secret-never-reflect"
    malformed = (
        b'{"revision_id":"40000000-0000-4000-8000-000000000004",'
        b'"recheck_provenance":{"grant":"'
        + secret.encode()
    )

    response = client.post(
        f"/api/v1/jobs/{JOB_ID}/revisions",
        content=malformed,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert secret not in response.text
    assert secret not in caplog.text


def test_revision_rejects_oversized_grant_without_reflecting_token(
    client,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "oversized-token-secret"
    provenance = {
        "grant": secret * 500,
        "result_document_id": "50000000-0000-4000-8000-000000000005",
        "result_verification_run_id": "60000000-0000-4000-8000-000000000006",
        "result_source_version": "sha256:" + "b" * 64,
    }
    response = client.post(
        f"/api/v1/jobs/{JOB_ID}/revisions",
        json={
            **payload(),
            "base_result": {
                "document_id": provenance["result_document_id"],
                "verification_run_id": provenance[
                    "result_verification_run_id"
                ],
                "source_version": provenance["result_source_version"],
            },
            "recheck_provenance": provenance,
        },
    )

    assert response.status_code == 422
    assert secret not in response.text
    assert secret not in caplog.text


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
        def persist(
            self,
            job_id: UUID,
            submission: ReviewRevisionSubmission,
        ) -> None:
            del job_id, submission
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
