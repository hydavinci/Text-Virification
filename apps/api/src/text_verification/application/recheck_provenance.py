from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID

from text_verification.domain.verification import MAX_RECHECK_GRANT_CHARS

_VERSION: Final = 1
_AUDIENCE: Final = "text-verification-recheck"
_CLAIM_KEYS: Final = {
    "aud",
    "exp",
    "iat",
    "job_id",
    "original_document_id",
    "original_source_version",
    "original_verification_run_id",
    "result_document_id",
    "result_source_version",
    "result_verification_run_id",
    "submitted_text_sha256",
    "v",
}


class RecheckGrantError(ValueError):
    pass


@dataclass(frozen=True)
class RecheckGrantBinding:
    job_id: UUID
    original_document_id: UUID
    original_verification_run_id: UUID
    original_source_version: str
    submitted_text: str
    result_document_id: UUID
    result_verification_run_id: UUID
    result_source_version: str


class RecheckProvenanceGrantService:
    def __init__(
        self,
        secret: str,
        *,
        ttl: timedelta = timedelta(minutes=15),
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        secret_bytes = secret.encode("utf-8")
        if len(secret_bytes) < 32:
            raise ValueError(
                "Recheck provenance secret must contain at least 32 UTF-8 bytes."
            )
        if ttl <= timedelta(0) or ttl > timedelta(hours=24):
            raise ValueError("Recheck provenance TTL must be within 24 hours.")
        self._secret = secret_bytes
        self._ttl = ttl
        self._now_factory = now_factory or (lambda: datetime.now(UTC))

    def issue(self, binding: RecheckGrantBinding) -> str:
        now = self._now()
        claims = {
            "aud": _AUDIENCE,
            "exp": int((now + self._ttl).timestamp()),
            "iat": int(now.timestamp()),
            "job_id": str(binding.job_id),
            "original_document_id": str(binding.original_document_id),
            "original_source_version": binding.original_source_version,
            "original_verification_run_id": str(
                binding.original_verification_run_id
            ),
            "result_document_id": str(binding.result_document_id),
            "result_source_version": binding.result_source_version,
            "result_verification_run_id": str(
                binding.result_verification_run_id
            ),
            "submitted_text_sha256": hashlib.sha256(
                binding.submitted_text.encode("utf-8")
            ).hexdigest(),
            "v": _VERSION,
        }
        payload = json.dumps(
            claims,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        encoded_payload = _encode(payload)
        signature = hmac.new(
            self._secret,
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        grant = f"{encoded_payload}.{_encode(signature)}"
        if len(grant) > MAX_RECHECK_GRANT_CHARS:
            raise RecheckGrantError("Recheck provenance grant is too large.")
        return grant

    def verify(
        self,
        grant: str,
        expected: RecheckGrantBinding,
    ) -> None:
        try:
            claims = self._verified_claims(grant)
            expected_claims = {
                "job_id": str(expected.job_id),
                "original_document_id": str(expected.original_document_id),
                "original_source_version": expected.original_source_version,
                "original_verification_run_id": str(
                    expected.original_verification_run_id
                ),
                "result_document_id": str(expected.result_document_id),
                "result_source_version": expected.result_source_version,
                "result_verification_run_id": str(
                    expected.result_verification_run_id
                ),
                "submitted_text_sha256": hashlib.sha256(
                    expected.submitted_text.encode("utf-8")
                ).hexdigest(),
            }
        except (UnicodeEncodeError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise RecheckGrantError(
                "Recheck provenance grant is invalid."
            ) from error
        if any(
            not hmac.compare_digest(str(claims[key]), value)
            for key, value in expected_claims.items()
        ):
            raise RecheckGrantError("Recheck provenance grant is invalid.")

    def _verified_claims(self, grant: str) -> dict[str, object]:
        if (
            not isinstance(grant, str)
            or not grant
            or len(grant) > MAX_RECHECK_GRANT_CHARS
            or grant.count(".") != 1
        ):
            raise RecheckGrantError("Recheck provenance grant is invalid.")
        encoded_payload, encoded_signature = grant.split(".")
        signature = _decode(encoded_signature, maximum=64)
        expected_signature = hmac.new(
            self._secret,
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(signature, expected_signature):
            raise RecheckGrantError("Recheck provenance grant is invalid.")
        payload = _decode(encoded_payload, maximum=4096)
        claims = json.loads(payload)
        if not isinstance(claims, dict) or set(claims) != _CLAIM_KEYS:
            raise RecheckGrantError("Recheck provenance grant is invalid.")
        issued_at = claims["iat"]
        expires_at = claims["exp"]
        if (
            isinstance(issued_at, bool)
            or not isinstance(issued_at, int)
            or isinstance(expires_at, bool)
            or not isinstance(expires_at, int)
            or claims["v"] != _VERSION
            or claims["aud"] != _AUDIENCE
        ):
            raise RecheckGrantError("Recheck provenance grant is invalid.")
        now = int(self._now().timestamp())
        ttl_seconds = int(self._ttl.total_seconds())
        if (
            issued_at > now
            or expires_at <= now
            or expires_at <= issued_at
            or expires_at - issued_at > ttl_seconds
        ):
            raise RecheckGrantError("Recheck provenance grant is invalid.")
        for key in _CLAIM_KEYS - {"iat", "exp", "v"}:
            if not isinstance(claims[key], str):
                raise RecheckGrantError("Recheck provenance grant is invalid.")
        for key in {
            "job_id",
            "original_document_id",
            "original_verification_run_id",
            "result_document_id",
            "result_verification_run_id",
        }:
            value = str(claims[key])
            if str(UUID(value)) != value:
                raise RecheckGrantError("Recheck provenance grant is invalid.")
        digest = claims["submitted_text_sha256"]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise RecheckGrantError("Recheck provenance grant is invalid.")
        return claims

    def _now(self) -> datetime:
        now = self._now_factory()
        if now.tzinfo is None:
            raise ValueError("Recheck provenance clock must be timezone-aware.")
        return now.astimezone(UTC)


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str, *, maximum: int) -> bytes:
    if not value or len(value) > maximum * 2:
        raise RecheckGrantError("Recheck provenance grant is invalid.")
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(
        value + padding,
        altchars=b"-_",
        validate=True,
    )
