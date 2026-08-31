from collections.abc import Iterator
from typing import Annotated, cast

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from text_verification.application.verification_pipeline import VerificationPipeline
from text_verification.config import Settings, get_settings
from text_verification.infrastructure.database import get_session_factory
from text_verification.infrastructure.repositories import JobRepository
from text_verification.infrastructure.storage import JobStorage


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
