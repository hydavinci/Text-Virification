from __future__ import annotations

import hashlib
from bisect import bisect_right
from collections import deque
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from text_verification.application.errors import VerificationError
from text_verification.application.recheck_provenance import (
    RecheckGrantBinding,
    RecheckGrantError,
    RecheckProvenanceGrantService,
)
from text_verification.domain.text_edits import (
    MAX_REVISION_TEXT_CODEPOINTS,
    MAX_REVISION_TEXT_UTF8_BYTES,
    TextDiffLimitError,
    validate_revision_text,
)
from text_verification.domain.verification import (
    DocumentRevisionKind,
    PersistedDocumentRevision,
    ReviewRevisionDraft,
    ReviewRevisionSubmission,
    RevisionBaseResult,
    RevisionProvenanceKind,
    VerificationResult,
    VerifiedRevisionBaseResult,
    VerifiedRevisionProvenance,
)

MAX_REVIEW_DERIVATION_STATES = 100_000
MAX_REVIEW_DERIVATION_WORK = 25_000_000


class ReviewRevisionRepository(Protocol):
    def read_revision_result(
        self,
        job_id: UUID,
        verification_run_id: UUID,
    ) -> VerificationResult: ...

    def persist_review_revision(
        self,
        job_id: UUID,
        draft: ReviewRevisionDraft,
        *,
        created_at: datetime,
        verified_provenance: VerifiedRevisionProvenance,
    ) -> PersistedDocumentRevision: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


ReviewRevisionRepositoryFactory = Callable[
    [],
    AbstractContextManager[ReviewRevisionRepository],
]


class ReviewRevisionService:
    def __init__(
        self,
        repository_factory: ReviewRevisionRepositoryFactory,
        *,
        now_factory: Callable[[], datetime] | None = None,
        max_revision_bytes: int = MAX_REVISION_TEXT_UTF8_BYTES,
        max_revision_codepoints: int = MAX_REVISION_TEXT_CODEPOINTS,
        recheck_grant_service: RecheckProvenanceGrantService | None = None,
    ) -> None:
        self._repository_factory = repository_factory
        self._now_factory = now_factory or (lambda: datetime.now(UTC))
        self._max_revision_bytes = min(
            max_revision_bytes,
            MAX_REVISION_TEXT_UTF8_BYTES,
        )
        self._max_revision_codepoints = max_revision_codepoints
        self._recheck_grant_service = recheck_grant_service

    def persist(
        self,
        job_id: UUID,
        submission: ReviewRevisionSubmission | ReviewRevisionDraft,
    ) -> PersistedDocumentRevision:
        if not isinstance(submission, ReviewRevisionSubmission):
            raise VerificationError(
                "revision_authorization_required",
                "revision_persistence",
                "The revision must identify its trusted base verification result.",
                False,
            )
        draft = submission.draft()
        try:
            validate_revision_text(
                draft.text,
                max_codepoints=self._max_revision_codepoints,
                max_utf8_bytes=self._max_revision_bytes,
            )
        except TextDiffLimitError as error:
            raise VerificationError(
                "revision_text_too_large",
                "revision_persistence",
                "The revision text exceeds the configured size limit.",
                False,
            ) from error
        with self._repository_factory() as repository:
            try:
                original = repository.read_revision_result(
                    job_id,
                    draft.verification_run_id,
                )
                verified_provenance = self._authorize_submission(
                    job_id,
                    original,
                    submission,
                )
                persisted = repository.persist_review_revision(
                    job_id,
                    draft,
                    created_at=self._now_factory(),
                    verified_provenance=verified_provenance,
                )
                repository.commit()
                return persisted
            except VerificationError:
                repository.rollback()
                raise
            except LookupError as error:
                repository.rollback()
                raise VerificationError(
                    "revision_identity_not_found",
                    "revision_persistence",
                    "The verification result or parent revision was not found.",
                    False,
                ) from error
            except ValueError as error:
                repository.rollback()
                raise VerificationError(
                    "revision_conflict",
                    "revision_persistence",
                    "The revision conflicts with the persisted review history.",
                    False,
                ) from error
            except Exception as error:
                repository.rollback()
                raise VerificationError(
                    "revision_persistence_failed",
                    "revision_persistence",
                    "The revision could not be persisted.",
                    True,
                ) from error

    def _authorize_submission(
        self,
        job_id: UUID,
        original: VerificationResult,
        submission: ReviewRevisionSubmission,
    ) -> VerifiedRevisionProvenance:
        draft = submission.draft()
        if (
            draft.document_id != original.document_id
            or draft.verification_run_id != original.verification_run_id
            or draft.source_version != original.source_version
        ):
            raise VerificationError(
                "revision_identity_not_found",
                "revision_persistence",
                "The verification result or parent revision was not found.",
                False,
            )
        if _base_result_matches(submission.base_result, original):
            if (
                submission.recheck_provenance is not None
                or not _derives_from_original_result(original, draft)
            ):
                raise VerificationError(
                    "revision_authorization_required",
                    "revision_persistence",
                    "The revision text requires a valid recheck authorization.",
                    False,
                )
            return _verified_provenance(
                RevisionProvenanceKind.ORIGINAL_RESULT,
                job_id,
                submission.base_result,
                original.text,
                draft.text,
            )

        recheck = submission.recheck_provenance
        if recheck is None:
            raise VerificationError(
                "revision_authorization_required",
                "revision_persistence",
                "The revision text requires a valid recheck authorization.",
                False,
            )
        if (
            submission.base_result.document_id != recheck.result_document_id
            or submission.base_result.verification_run_id
            != recheck.result_verification_run_id
            or submission.base_result.source_version
            != recheck.result_source_version
        ):
            raise VerificationError(
                "recheck_provenance_invalid",
                "revision_persistence",
                "The recheck provenance grant is invalid or expired.",
                False,
            )
        if self._recheck_grant_service is None:
            raise VerificationError(
                "recheck_provenance_unavailable",
                "revision_persistence",
                "Secure recheck provenance is not configured.",
                True,
            )
        try:
            self._recheck_grant_service.verify(
                recheck.grant,
                RecheckGrantBinding(
                    job_id=job_id,
                    original_document_id=original.document_id,
                    original_verification_run_id=original.verification_run_id,
                    original_source_version=original.source_version,
                    submitted_text=draft.text,
                    result_document_id=recheck.result_document_id,
                    result_verification_run_id=(
                        recheck.result_verification_run_id
                    ),
                    result_source_version=recheck.result_source_version,
                ),
            )
        except RecheckGrantError as error:
            raise VerificationError(
                "recheck_provenance_invalid",
                "revision_persistence",
                "The recheck provenance grant is invalid or expired.",
                False,
            ) from error
        return _verified_provenance(
            RevisionProvenanceKind.RECHECK_RESULT,
            job_id,
            submission.base_result,
            draft.text,
            draft.text,
        )


def _base_result_matches(
    base_result: RevisionBaseResult,
    result: VerificationResult,
) -> bool:
    return (
        base_result.document_id == result.document_id
        and base_result.verification_run_id == result.verification_run_id
        and base_result.source_version == result.source_version
    )


def _verified_provenance(
    kind: RevisionProvenanceKind,
    job_id: UUID,
    base_result: RevisionBaseResult,
    base_text: str,
    revision_text: str,
) -> VerifiedRevisionProvenance:
    return VerifiedRevisionProvenance(
        kind=kind,
        job_id=job_id,
        base_result=VerifiedRevisionBaseResult(
            **base_result.model_dump(),
            text_sha256=_text_sha256(base_text),
        ),
        revision_text_sha256=_text_sha256(revision_text),
    )


def _text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _derives_from_original_result(
    result: VerificationResult,
    draft: ReviewRevisionDraft,
) -> bool:
    if draft.kind is not DocumentRevisionKind.REVIEW:
        return False
    if draft.text == result.text:
        return True

    replacements_by_start: dict[int, list[tuple[int, str]]] = {}
    for issue in result.issues:
        replacements = [
            replacement
            for replacement in (issue.suggestion, *issue.alternatives)
            if replacement is not None
        ]
        for replacement in dict.fromkeys(replacements):
            replacements_by_start.setdefault(issue.start, []).append(
                (issue.end, replacement)
            )
    if not replacements_by_start:
        return False

    issue_starts = sorted(replacements_by_start)
    source = result.text
    target = draft.text
    pending = deque([(0, 0)])
    visited: set[tuple[int, int]] = set()
    work = 0

    def charge(units: int) -> bool:
        nonlocal work
        work += units
        return work <= MAX_REVIEW_DERIVATION_WORK

    while pending:
        source_index, target_index = pending.popleft()
        state = (source_index, target_index)
        if state in visited:
            continue
        visited.add(state)
        if len(visited) > MAX_REVIEW_DERIVATION_STATES:
            return False
        if source_index == len(source):
            if target_index == len(target):
                return True
            continue
        if source_index > len(source) or target_index > len(target):
            continue

        for source_end, replacement in replacements_by_start.get(
            source_index,
            (),
        ):
            if not charge(len(replacement) + 1):
                return False
            if target.startswith(replacement, target_index):
                pending.append(
                    (source_end, target_index + len(replacement))
                )

        next_start_index = bisect_right(issue_starts, source_index)
        next_source_index = (
            issue_starts[next_start_index]
            if next_start_index < len(issue_starts)
            else len(source)
        )
        unchanged = source[source_index:next_source_index]
        if not charge(len(unchanged) + 1):
            return False
        if target.startswith(unchanged, target_index):
            pending.append(
                (next_source_index, target_index + len(unchanged))
            )
    return False
