from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.engine.url import make_url

from alembic import command

BACKEND_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def migration_database(test_database_url: str) -> Iterator[tuple[Config, Engine]]:
    schema_name = f"test_alembic_version_{uuid4().hex}"
    admin_engine = create_engine(test_database_url, pool_pre_ping=True)
    schema_url = make_url(test_database_url).update_query_dict(
        {"options": f"-csearch_path={schema_name}"}
    ).render_as_string(hide_password=False)
    engine = create_engine(schema_url, pool_pre_ping=True)
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.attributes["database_url"] = schema_url

    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
        yield config, engine
    finally:
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
        admin_engine.dispose()


def test_fresh_database_supports_long_revision_ids(
    migration_database: tuple[Config, Engine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, engine = migration_database
    monkeypatch.chdir(BACKEND_ROOT.parents[1])

    command.upgrade(config, "head")

    with engine.connect() as connection:
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()

    assert revision == "0012_add_revision_provenance"
    assert _version_column_length(engine) == 128


def test_existing_varchar_32_version_table_is_widened_before_upgrade(
    migration_database: tuple[Config, Engine],
) -> None:
    config, engine = migration_database
    command.upgrade(config, "0003_add_job_leases")
    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE alembic_version "
                "ALTER COLUMN version_num TYPE VARCHAR(32)"
            )
        )

    assert _version_column_length(engine) == 32

    command.upgrade(config, "head")

    assert _version_column_length(engine) == 128


@pytest.mark.parametrize(
    ("column_type", "expected_length"),
    [("VARCHAR(256)", 256), ("TEXT", None)],
)
def test_existing_wider_version_table_is_preserved(
    migration_database: tuple[Config, Engine],
    column_type: str,
    expected_length: int | None,
) -> None:
    config, engine = migration_database
    command.upgrade(config, "0003_add_job_leases")
    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE alembic_version "
                f"ALTER COLUMN version_num TYPE {column_type}"
            )
        )

    command.upgrade(config, "head")

    assert _version_column_length(engine) == expected_length


def _version_column_length(engine: Engine) -> int | None:
    columns = inspect(engine).get_columns("alembic_version")
    return next(
        column["type"].length
        for column in columns
        if column["name"] == "version_num"
    )
