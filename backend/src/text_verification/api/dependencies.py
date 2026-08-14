from collections.abc import Iterator

from sqlalchemy.orm import Session

from text_verification.infrastructure.database import get_session_factory


def get_session() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def get_db_session() -> Iterator[Session]:
    yield from get_session()
