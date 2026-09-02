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
from text_verification.domain.verification import Scenario, VerificationOptions
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


def test_to_job_read_decodes_persisted_nondefault_verification_options() -> None:
    now = datetime.now(UTC)
    row = JobRow(
        job_id=uuid4(),
        source_name="sample.txt",
        file_type=FileType.TXT.value,
        size_bytes=4,
        storage_key=str(uuid4()),
        status=JobStatus.QUEUED.value,
        progress=0,
        error_code=None,
        error_message=None,
        error_stage=None,
        error_retryable=None,
        verification_options={
            "scenario": "legal",
            "enable_security": False,
            "enable_sensitive": True,
            "enable_ad_extreme": False,
            "custom_glossary": [],
            "banned_words": ["forbidden"],
        },
        created_at=now,
        updated_at=now,
        expires_at=now + timedelta(hours=1),
        lease_owner_token=None,
        lease_expires_at=None,
        rescue_due_at=now,
        rescue_attempts=0,
        rescue_last_published_at=None,
    )

    job = JobRepository(_unexpected_session())._to_job_read(row)

    assert job.verification_options == VerificationOptions(
        scenario=Scenario.LEGAL,
        enable_security=False,
        banned_words=("forbidden",),
    )


def test_to_job_read_maps_legacy_empty_options_to_fresh_defaults() -> None:
    now = datetime.now(UTC)
    row = JobRow(
        job_id=uuid4(),
        source_name="legacy.txt",
        file_type=FileType.TXT.value,
        size_bytes=4,
        storage_key=str(uuid4()),
        status=JobStatus.QUEUED.value,
        progress=0,
        error_code=None,
        error_message=None,
        error_stage=None,
        error_retryable=None,
        verification_options={},
        created_at=now,
        updated_at=now,
        expires_at=now + timedelta(hours=1),
        lease_owner_token=None,
        lease_expires_at=None,
        rescue_due_at=now,
        rescue_attempts=0,
        rescue_last_published_at=None,
    )
    repository = JobRepository(_unexpected_session())

    first = repository._to_job_read(row).verification_options
    second = repository._to_job_read(row).verification_options

    assert first == VerificationOptions()
    assert second == VerificationOptions()
    assert first is not second


def test_expire_mapping_constructs_valid_job_event_without_job_only_fields() -> None:
    now = datetime.now(UTC)
    row = JobRow(
        job_id=uuid4(),
        source_name="sample.txt",
        file_type=FileType.TXT.value,
        size_bytes=4,
        storage_key=str(uuid4()),
        status=JobStatus.QUEUED.value,
        progress=25,
        error_code=None,
        error_message=None,
        error_stage=None,
        error_retryable=None,
        verification_options={},
        created_at=now - timedelta(hours=2),
        updated_at=now - timedelta(hours=2),
        expires_at=now - timedelta(hours=1),
        lease_owner_token=None,
        lease_expires_at=None,
        rescue_due_at=now - timedelta(hours=1),
        rescue_attempts=0,
        rescue_last_published_at=None,
    )
    session = _ExpireSession(row)

    expired = JobRepository(cast(Session, session)).expire_jobs_before(now)

    assert expired == [row.job_id]
    assert row.status == JobStatus.EXPIRED.value
    assert len(session.added) == 1
    assert isinstance(session.added[0], JobEventRow)
    assert not hasattr(session.added[0], "verification_options")


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


class _ScalarRows:
    def __init__(self, row: JobRow) -> None:
        self._row = row

    def all(self) -> list[JobRow]:
        return [self._row]


class _ExpireSession:
    def __init__(self, row: JobRow) -> None:
        self.row = row
        self.added: list[object] = []
        self.scalar_calls = 0

    def scalars(self, statement: object) -> _ScalarRows:
        del statement
        return _ScalarRows(self.row)

    def scalar(self, statement: object) -> int:
        del statement
        self.scalar_calls += 1
        return 1

    def add(self, value: object) -> None:
        self.added.append(value)

    def flush(self) -> None:
        return None


def _load_migration() -> ModuleType:
    spec = spec_from_file_location("task4_migration_0002", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"unable to load migration: {MIGRATION_PATH}")
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration
