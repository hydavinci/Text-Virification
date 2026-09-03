from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from text_verification.application.errors import VerificationError
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
    ) -> None:
        self._repository_factory = repository_factory
        self._now_factory = now_factory or (lambda: datetime.now(UTC))

    def persist(
        self,
        job_id: UUID,
        draft: ReviewRevisionDraft,
    ) -> PersistedDocumentRevision:
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
