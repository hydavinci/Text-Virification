from __future__ import annotations

from datetime import UTC, datetime, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import String, Text
from sqlalchemy.orm import Session

from text_verification.domain.documents import FileType
from text_verification.domain.jobs import JobStatus
from text_verification.infrastructure.orm import JobEventRow, JobRow
from text_verification.infrastructure.repositories import JobRepository

BACKEND_ROOT = Path(__file__).resolve().parents[3]
MIGRATION_PATH = BACKEND_ROOT / "alembic/versions/0002_add_verification_results.py"


@pytest.mark.parametrize(
    ("column", "expected_length"),
    [
        (JobRow.__table__.c.source_name, 255),
        (JobRow.__table__.c.error_code, 64),
        (JobEventRow.__table__.c.message, 255),
    ],
    ids=lambda value: getattr(value, "name", str(value)),
)
def test_existing_job_string_columns_match_0001(
    column: object,
    expected_length: int,
) -> None:
    assert isinstance(column.type, String)  # type: ignore[attr-defined]
    assert column.type.length == expected_length  # type: ignore[attr-defined]


def test_existing_error_message_remains_unbounded_text() -> None:
    assert isinstance(JobRow.__table__.c.error_message.type, Text)


def test_migration_0002_does_not_alter_existing_job_tables() -> None:
    migration = _load_migration()
    recorder = _OperationRecorder()
    migration.op = recorder

    migration.upgrade()
    migration.downgrade()

    assert recorder.altered_columns == []
    assert recorder.created_tables == [
        "documents",
        "verification_runs",
        "verification_issues",
        "review_revisions",
        "export_artifacts",
    ]
    assert recorder.dropped_tables == [
        "export_artifacts",
        "review_revisions",
        "verification_issues",
        "verification_runs",
        "documents",
    ]


def test_create_job_rejects_source_name_longer_than_database_limit() -> None:
    repository = JobRepository(_unexpected_session())
    now = datetime.now(UTC)

    with pytest.raises(ValueError, match="source_name"):
        repository.create_job(
            job_id=uuid4(),
            source_name="s" * 256,
            file_type=FileType.DOCX,
            size_bytes=1,
            storage_key=str(uuid4()),
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )


@pytest.mark.parametrize(
    ("message", "error_code", "expected_field"),
    [
        ("m" * 256, None, "message"),
        ("valid", "e" * 65, "error_code"),
    ],
)
def test_transition_rejects_values_longer_than_database_limits_before_locking(
    message: str,
    error_code: str | None,
    expected_field: str,
) -> None:
    repository = JobRepository(_unexpected_session())

    with pytest.raises(ValueError, match=expected_field):
        repository.transition(
            uuid4(),
            JobStatus.PARSING,
            25,
            message,
            error_code=error_code,
            error_message="unbounded",
        )


class _OperationRecorder:
    def __init__(self) -> None:
        self.altered_columns: list[tuple[str, str]] = []
        self.created_tables: list[str] = []
        self.dropped_tables: list[str] = []

    def alter_column(self, table_name: str, column_name: str, **kwargs: object) -> None:
        del kwargs
        self.altered_columns.append((table_name, column_name))

    def create_table(self, table_name: str, *args: object, **kwargs: object) -> None:
        del args, kwargs
        self.created_tables.append(table_name)

    def drop_table(self, table_name: str) -> None:
        self.dropped_tables.append(table_name)


class _UnexpectedSessionUse:
    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"database session used before boundary validation: {name}")


def _unexpected_session() -> Session:
    return cast(Session, _UnexpectedSessionUse())


def _load_migration() -> ModuleType:
    spec = spec_from_file_location("task4_migration_0002", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"unable to load migration: {MIGRATION_PATH}")
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration
