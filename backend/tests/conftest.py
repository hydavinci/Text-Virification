import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from text_verification.main import create_app

BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def app() -> Iterator[FastAPI]:
    application = create_app()
    try:
        yield application
    finally:
        application.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def test_database_url() -> str:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip(
            "TEST_DATABASE_URL is not set; PostgreSQL integration tests require a real database."
        )
    return database_url


@pytest.fixture(scope="session")
def test_database_schema_name() -> str:
    return f"test_job_repository_{uuid4().hex}"


def _schema_database_url(database_url: str, schema_name: str) -> str:
    return str(
        make_url(database_url).update_query_dict({"options": f"-csearch_path={schema_name}"})
    )


@pytest.fixture(scope="session")
def alembic_config(
    test_database_url: str, test_database_schema_name: str
) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.attributes["database_url"] = _schema_database_url(
        test_database_url,
        test_database_schema_name,
    )
    return config


@pytest.fixture(scope="session")
def db_engine(
    test_database_url: str,
    test_database_schema_name: str,
    alembic_config: Config,
) -> Iterator[Engine]:
    admin_engine = create_engine(test_database_url, pool_pre_ping=True)
    schema_url = _schema_database_url(test_database_url, test_database_schema_name)
    engine: Engine | None = None

    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{test_database_schema_name}"'))
        command.upgrade(alembic_config, "head")
        engine = create_engine(schema_url, pool_pre_ping=True)
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{test_database_schema_name}" CASCADE'))
        admin_engine.dispose()


@pytest.fixture
def db_session_factory(db_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def db_session(db_session_factory: sessionmaker[Session], db_engine: Engine) -> Iterator[Session]:
    session = db_session_factory()
    try:
        yield session
    finally:
        session.close()
        with db_engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE job_events, jobs RESTART IDENTITY CASCADE"))
