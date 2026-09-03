from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from text_verification.application.recheck_provenance import (
    RecheckGrantBinding,
    RecheckGrantError,
    RecheckProvenanceGrantService,
)

NOW = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)
SECRET = "server-owned-recheck-grant-secret-32-bytes"


def binding() -> RecheckGrantBinding:
    return RecheckGrantBinding(
        job_id=UUID("10000000-0000-4000-8000-000000000001"),
        original_document_id=UUID("10000000-0000-4000-8000-000000000001"),
        original_verification_run_id=UUID(
            "20000000-0000-4000-8000-000000000002"
        ),
        original_source_version="sha256:" + "a" * 64,
        submitted_text="重新检查文本",
        result_document_id=UUID("30000000-0000-4000-8000-000000000003"),
        result_verification_run_id=UUID(
            "40000000-0000-4000-8000-000000000004"
        ),
        result_source_version="sha256:" + "b" * 64,
    )


def service(*, now: datetime = NOW) -> RecheckProvenanceGrantService:
    return RecheckProvenanceGrantService(
        SECRET,
        ttl=timedelta(minutes=10),
        now_factory=lambda: now,
    )


def test_valid_server_grant_verifies_for_its_exact_binding() -> None:
    expected = binding()

    grant = service().issue(expected)

    service().verify(grant, expected)


@pytest.mark.parametrize(
    "changed",
    [
        {"job_id": UUID("90000000-0000-4000-8000-000000000009")},
        {
            "original_verification_run_id": UUID(
                "90000000-0000-4000-8000-000000000009"
            )
        },
        {"submitted_text": "另一段文本"},
        {"result_document_id": UUID("90000000-0000-4000-8000-000000000009")},
        {
            "result_verification_run_id": UUID(
                "90000000-0000-4000-8000-000000000009"
            )
        },
        {"result_source_version": "sha256:" + "c" * 64},
    ],
)
def test_grant_rejects_cross_job_run_text_and_result_replay(
    changed: dict[str, object],
) -> None:
    original = binding()
    grant = service().issue(original)

    with pytest.raises(RecheckGrantError):
        service().verify(grant, replace(original, **changed))


def test_grant_rejects_tampered_claims_and_signature() -> None:
    expected = binding()
    grant = service().issue(expected)
    payload, signature = grant.split(".")
    decoded = json.loads(_decode(payload))
    decoded["result_source_version"] = "sha256:" + "c" * 64
    tampered_payload = _encode(
        json.dumps(
            decoded,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )

    with pytest.raises(RecheckGrantError):
        service().verify(f"{tampered_payload}.{signature}", expected)
    with pytest.raises(RecheckGrantError):
        service().verify(f"{payload}.{signature[:-1]}A", expected)


def test_unkeyed_client_recomputation_is_rejected() -> None:
    expected = binding()
    legitimate = service().issue(expected)
    payload, _signature = legitimate.split(".")
    forged_signature = _encode(hashlib.sha256(_decode(payload)).digest())

    with pytest.raises(RecheckGrantError):
        service().verify(f"{payload}.{forged_signature}", expected)


def test_expired_grant_is_rejected() -> None:
    expected = binding()
    grant = service().issue(expected)

    with pytest.raises(RecheckGrantError):
        service(now=NOW + timedelta(minutes=11)).verify(grant, expected)


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
