from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from text_verification.application.errors import VerificationError
from text_verification.application.recheck_provenance import (
    RecheckGrantBinding,
    RecheckProvenanceGrantService,
)
from text_verification.application.verification_pipeline import (
    VerificationCommand,
    VerificationPipeline,
)
from text_verification.compatibility.service import direct_text_document_id
from text_verification.domain.documents import FileType
from text_verification.domain.text_edits import (
    MAX_REVISION_TEXT_CODEPOINTS,
    TextDiffLimitError,
    validate_revision_text,
)
from text_verification.domain.verification import (
    VerificationExecutionMode,
    VerificationOptions,
    VerificationResult,
)
from text_verification.infrastructure.verification_repository import (
    JobResultSnapshot,
    JobResultState,
)


class JobRecheckRepository(Protocol):
    def read_result_snapshot(self, job_id: UUID) -> JobResultSnapshot: ...

    def rollback(self) -> None: ...


JobRecheckRepositoryFactory = Callable[
    [],
    AbstractContextManager[JobRecheckRepository],
]


@dataclass(frozen=True)
class JobRecheckResult:
    result: VerificationResult
    grant: str


class JobRecheckService:
    def __init__(
        self,
        repository_factory: JobRecheckRepositoryFactory,
        pipeline: VerificationPipeline,
        grant_service: RecheckProvenanceGrantService | None,
        *,
        max_text_bytes: int,
    ) -> None:
        self._repository_factory = repository_factory
        self._pipeline = pipeline
        self._grant_service = grant_service
        self._max_text_bytes = max_text_bytes

    def recheck(
        self,
        job_id: UUID,
        text: str,
        options: VerificationOptions,
    ) -> JobRecheckResult:
        if self._grant_service is None:
            raise VerificationError(
                "recheck_provenance_unavailable",
                "validation",
                "Secure recheck provenance is not configured.",
                True,
            )
        if not text.strip():
            raise VerificationError(
                "recheck_text_invalid",
                "validation",
                "Recheck text must not be empty.",
                False,
            )
        try:
            validate_revision_text(
                text,
                max_codepoints=MAX_REVISION_TEXT_CODEPOINTS,
                max_utf8_bytes=self._max_text_bytes,
            )
        except TextDiffLimitError as error:
            raise VerificationError(
                "revision_text_too_large",
                "validation",
                "The recheck text exceeds the configured size limit.",
                False,
            ) from error
        with self._repository_factory() as repository:
            try:
                snapshot = repository.read_result_snapshot(job_id)
            finally:
                repository.rollback()
        original = _ready_result(snapshot)
        if original.document_id != job_id:
            raise VerificationError(
                "recheck_identity_mismatch",
                "validation",
                "The job result does not belong to the requested job.",
                False,
            )
        fresh = self._pipeline.run(
            VerificationCommand(
                document_id=direct_text_document_id(text),
                source_path=None,
                direct_text=text,
                source_name="直接输入文本",
                file_type=FileType.TXT,
                options=options,
                execution_mode=VerificationExecutionMode.SYNCHRONOUS,
            )
        )
        if (
            fresh.execution_mode is not VerificationExecutionMode.SYNCHRONOUS
            or fresh.text != text
        ):
            raise VerificationError(
                "recheck_result_mismatch",
                "checking",
                "The recheck result does not match the submitted text.",
                False,
            )
        grant = self._grant_service.issue(
            RecheckGrantBinding(
                job_id=job_id,
                original_document_id=original.document_id,
                original_verification_run_id=original.verification_run_id,
                original_source_version=original.source_version,
                submitted_text=text,
                result_document_id=fresh.document_id,
                result_verification_run_id=fresh.verification_run_id,
                result_source_version=fresh.source_version,
            )
        )
        return JobRecheckResult(fresh, grant)


def _ready_result(snapshot: JobResultSnapshot) -> VerificationResult:
    if snapshot.state is JobResultState.MISSING:
        raise VerificationError(
            "job_not_found",
            "validation",
            "Job was not found.",
            False,
        )
    if snapshot.state is JobResultState.EXPIRED:
        raise VerificationError(
            "job_result_expired",
            "validation",
            "Job result has expired.",
            False,
        )
    if snapshot.state is not JobResultState.READY or snapshot.result is None:
        raise VerificationError(
            "job_result_unavailable",
            "validation",
            "Job result is not available for recheck.",
            False,
        )
    return snapshot.result
