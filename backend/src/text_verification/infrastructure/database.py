from functools import cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from text_verification.config import Settings, get_settings


@cache
def _get_engine(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True)


@cache
def _get_session_factory(database_url: str) -> sessionmaker[Session]:
    return sessionmaker(
        bind=_get_engine(database_url),
        autoflush=False,
        expire_on_commit=False,
    )


def get_engine(settings: Settings | None = None) -> Engine:
    resolved_settings = settings or get_settings()
    return _get_engine(resolved_settings.database_url)


def get_session_factory(settings: Settings | None = None) -> sessionmaker[Session]:
    resolved_settings = settings or get_settings()
    return _get_session_factory(resolved_settings.database_url)
