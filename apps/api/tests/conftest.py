import os
import socket
import subprocess
import time
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
from text_verification.config import get_settings
from text_verification.infrastructure.database import _get_engine, _get_session_factory
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
    if database_url:
        return database_url

    container_name = f"text-verification-test-pg16-{uuid4().hex[:12]}"
    port = _reserve_local_port()
    database_url = f"postgresql+psycopg://postgres:postgres@127.0.0.1:{port}/text_verification"
    original_database_url = os.environ.get("DATABASE_URL")
    started = False

    try:
        subprocess.run(
            [
                "docker",
                "run",
                "--detach",
                "--name",
                container_name,
                "--publish",
                f"{port}:5432",
                "--env",
                "POSTGRES_PASSWORD=postgres",
                "--env",
                "POSTGRES_DB=text_verification",
                "--health-cmd",
                "pg_isready -U postgres -d text_verification",
                "--health-interval",
                "1s",
                "--health-timeout",
                "5s",
                "--health-retries",
                "60",
                "postgres:16",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        started = True
        _wait_for_healthy_postgres(container_name)
        _wait_for_database_connection(database_url)
        os.environ["TEST_DATABASE_URL"] = database_url
        os.environ["DATABASE_URL"] = database_url
        _reset_database_caches()
        yield database_url
    finally:
        if original_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original_database_url
        os.environ.pop("TEST_DATABASE_URL", None)
        _reset_database_caches()
        if started:
            subprocess.run(
                ["docker", "rm", "--force", container_name],
                check=False,
                capture_output=True,
                text=True,
            )


@pytest.fixture(scope="session")
def test_database_schema_name() -> str:
    return f"test_job_repository_{uuid4().hex}"


def _schema_database_url(database_url: str, schema_name: str) -> str:
    return make_url(database_url).update_query_dict(
        {"options": f"-csearch_path={schema_name}"}
    ).render_as_string(hide_password=False)


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


def _reserve_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_healthy_postgres(container_name: str) -> None:
    deadline = time.monotonic() + 90
    last_status = "unknown"
    while time.monotonic() < deadline:
        status = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
                container_name,
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        last_status = status or last_status
        if status == "healthy":
            return
        time.sleep(1)
    raise RuntimeError(
        f"Temporary PostgreSQL container {container_name} did not become healthy "
        f"(last status: {last_status})."
    )


def _wait_for_database_connection(database_url: str) -> None:
    deadline = time.monotonic() + 30
    last_error = "unknown"
    while time.monotonic() < deadline:
        engine = create_engine(database_url, pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return
        except Exception as error:  # pragma: no cover - exercised only on slow Docker starts
            last_error = str(error)
            time.sleep(1)
        finally:
            engine.dispose()
    raise RuntimeError(
        "Temporary PostgreSQL database did not accept connections within 30 seconds "
        f"({last_error})."
    )


def _reset_database_caches() -> None:
    get_settings.cache_clear()
    _get_engine.cache_clear()
    _get_session_factory.cache_clear()
