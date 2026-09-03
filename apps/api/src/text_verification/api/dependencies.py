from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Annotated, cast

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from text_verification.application.factory import build_default_exporter_registry
from text_verification.application.job_recheck import (
    JobRecheckRepositoryFactory,
    JobRecheckService,
)
from text_verification.application.recheck_provenance import (
    RecheckProvenanceGrantService,
)
from text_verification.application.reconstruction_export import (
    ReconstructionExportService,
    ReconstructionRepositoryFactory,
)
from text_verification.application.review_revision import (
    ReviewRevisionRepositoryFactory,
    ReviewRevisionService,
)
from text_verification.application.verification_pipeline import VerificationPipeline
from text_verification.config import Settings, get_settings
from text_verification.infrastructure.database import get_session_factory
from text_verification.infrastructure.repositories import JobRepository
from text_verification.infrastructure.storage import JobStorage
from text_verification.infrastructure.verification_repository import VerificationRepository


def get_session() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def get_db_session() -> Iterator[Session]:
    yield from get_session()


def get_job_repository(
    session: Annotated[Session, Depends(get_db_session)],
) -> JobRepository:
    return JobRepository(session)


def get_job_storage(
    settings: Annotated[Settings, Depends(get_settings)],
) -> JobStorage:
    return JobStorage(settings.storage_root, settings.max_upload_bytes)


def get_verification_pipeline(request: Request) -> VerificationPipeline:
    return cast(VerificationPipeline, request.app.state.verification_pipeline)


def get_recheck_provenance_grant_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> RecheckProvenanceGrantService | None:
    secret = settings.recheck_grant_secret.get_secret_value()
    if len(secret.encode("utf-8")) < 32:
        return None
    return RecheckProvenanceGrantService(
        secret,
        ttl=timedelta(seconds=settings.recheck_grant_ttl_seconds),
    )


def get_reconstruction_export_service(
    storage: Annotated[JobStorage, Depends(get_job_storage)],
    grant_service: Annotated[
        RecheckProvenanceGrantService | None,
        Depends(get_recheck_provenance_grant_service),
    ],
) -> ReconstructionExportService:
    session_factory = get_session_factory()

    @contextmanager
    def repository_factory() -> Iterator[VerificationRepository]:
        session = session_factory()
        try:
            yield VerificationRepository(session)
        finally:
            session.close()

    return ReconstructionExportService(
        storage,
        cast(ReconstructionRepositoryFactory, repository_factory),
        exporter_registry_factory=lambda resolver: build_default_exporter_registry(
            anchored_source_resolver=resolver,
            max_output_bytes=storage.max_document_bytes,
        ),
        recheck_grant_service=grant_service,
    )


def get_job_recheck_service(
    pipeline: Annotated[
        VerificationPipeline,
        Depends(get_verification_pipeline),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
    grant_service: Annotated[
        RecheckProvenanceGrantService | None,
        Depends(get_recheck_provenance_grant_service),
    ],
) -> JobRecheckService:
    session_factory = get_session_factory()

    @contextmanager
    def repository_factory() -> Iterator[VerificationRepository]:
        session = session_factory()
        try:
            yield VerificationRepository(session)
        finally:
            session.close()

    return JobRecheckService(
        cast(JobRecheckRepositoryFactory, repository_factory),
        pipeline,
        grant_service,
        max_text_bytes=settings.max_upload_bytes,
    )


def get_review_revision_service(
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    grant_service: Annotated[
        RecheckProvenanceGrantService | None,
        Depends(get_recheck_provenance_grant_service),
    ],
) -> ReviewRevisionService:
    @contextmanager
    def repository_factory() -> Iterator[VerificationRepository]:
        yield VerificationRepository(session)

    return ReviewRevisionService(
        cast(ReviewRevisionRepositoryFactory, repository_factory),
        max_revision_bytes=settings.max_upload_bytes,
        recheck_grant_service=grant_service,
    )
