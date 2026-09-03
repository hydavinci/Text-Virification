from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from text_verification.application.errors import VerificationError
from text_verification.domain.text_edits import (
    MAX_REVISION_TEXT_CODEPOINTS,
    MAX_REVISION_TEXT_UTF8_BYTES,
    TextDiffLimitError,
    validate_revision_text,
)
from text_verification.domain.verification import (
    PersistedDocumentRevision,
    ReviewRevisionDraft,
)


class ReviewRevisionRepository(Protocol):
    def persist_review_revision(
        self,
        job_id: UUID,
        draft: ReviewRevisionDraft,
        *,
        created_at: datetime,
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
    ) -> None:
        self._repository_factory = repository_factory
        self._now_factory = now_factory or (lambda: datetime.now(UTC))
        self._max_revision_bytes = min(
            max_revision_bytes,
            MAX_REVISION_TEXT_UTF8_BYTES,
        )
        self._max_revision_codepoints = max_revision_codepoints

    def persist(
        self,
        job_id: UUID,
        draft: ReviewRevisionDraft,
    ) -> PersistedDocumentRevision:
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
                persisted = repository.persist_review_revision(
                    job_id,
                    draft,
                    created_at=self._now_factory(),
                )
                repository.commit()
                return persisted
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
