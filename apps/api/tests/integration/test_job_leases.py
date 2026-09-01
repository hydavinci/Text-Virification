from __future__ import annotations

from datetime import UTC, datetime, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType
from uuid import UUID, uuid4

import pytest
from sqlalchemy import CheckConstraint, Engine, inspect
from sqlalchemy.orm import Session
from sqlalchemy.orm.session import sessionmaker

from text_verification.domain.jobs import (
    JobClaimDisposition,
    JobLeaseLostError,
    JobStateConflictError,
    JobStatus,
)
from text_verification.infrastructure.orm import JobRow
from text_verification.infrastructure.repositories import JobRepository

BACKEND_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = BACKEND_ROOT / "alembic/versions/0003_add_job_leases.py"


def test_job_orm_and_migration_define_paired_lease_fields() -> None:
    assert {"lease_owner_token", "lease_expires_at"} <= set(JobRow.__table__.c.keys())
    assert {
        constraint.name
        for constraint in JobRow.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    } >= {"ck_jobs_lease_pair"}
    assert {index.name for index in JobRow.__table__.indexes} >= {
        "ix_jobs_lease_expires_at"
    }

    migration = _load_migration()
    assert migration.revision == "0003_add_job_leases"
    assert migration.down_revision == "0002_add_verification_results"


def test_database_schema_contains_job_lease_fields(db_engine: Engine) -> None:
    inspector = inspect(db_engine)
    columns = {column["name"] for column in inspector.get_columns("jobs")}

    assert {"lease_owner_token", "lease_expires_at"} <= columns
    assert {index["name"] for index in inspector.get_indexes("jobs")} >= {
        "ix_jobs_lease_expires_at"
    }
    assert {constraint["name"] for constraint in inspector.get_check_constraints("jobs")} >= {
        "ck_jobs_lease_pair"
    }


def test_live_lease_makes_duplicate_delivery_explicit_noop(
    db_session_factory: sessionmaker[Session],
) -> None:
    job_id = uuid4()
    first_owner = uuid4()
    second_owner = uuid4()
    now = datetime.now(UTC)
    _seed_job(db_session_factory, job_id, expires_at=now + timedelta(hours=1))

    first_session = db_session_factory()
    second_session = db_session_factory()
    try:
        first = JobRepository(first_session).acquire_lease(
            job_id,
            owner_token=first_owner,
            now=now,
            lease_expires_at=now + timedelta(minutes=20),
        )
        first_session.commit()

        duplicate = JobRepository(second_session).acquire_lease(
            job_id,
            owner_token=second_owner,
            now=now + timedelta(seconds=1),
            lease_expires_at=now + timedelta(minutes=20, seconds=1),
        )
        second_session.commit()
    finally:
        first_session.close()
        second_session.close()

    assert first.disposition is JobClaimDisposition.ACQUIRED
    assert duplicate.disposition is JobClaimDisposition.LEASED
    assert duplicate.job is not None
    assert duplicate.job.status is JobStatus.QUEUED


def test_expired_lease_allows_new_delivery_takeover(
    db_session_factory: sessionmaker[Session],
) -> None:
    job_id = uuid4()
    first_owner = uuid4()
    second_owner = uuid4()
    now = datetime.now(UTC)
    _seed_job(db_session_factory, job_id, expires_at=now + timedelta(hours=1))

    first_session = db_session_factory()
    second_session = db_session_factory()
    verification_session = db_session_factory()
    try:
        first_repository = JobRepository(first_session)
        first_repository.acquire_lease(
            job_id,
            owner_token=first_owner,
            now=now,
            lease_expires_at=now + timedelta(seconds=1),
        )
        first_repository.commit()

        takeover = JobRepository(second_session).acquire_lease(
            job_id,
            owner_token=second_owner,
            now=now + timedelta(seconds=2),
            lease_expires_at=now + timedelta(minutes=20),
        )
        second_session.commit()

        row = verification_session.get(JobRow, job_id)
        assert row is not None
        verification_session.refresh(row)
    finally:
        first_session.close()
        second_session.close()
        verification_session.close()

    assert takeover.disposition is JobClaimDisposition.ACQUIRED
    assert row.lease_owner_token == second_owner


def test_retry_rotates_predecessor_lease_only_once(
    db_session_factory: sessionmaker[Session],
) -> None:
    job_id = uuid4()
    first_owner = uuid4()
    retry_owner = uuid4()
    duplicate_retry_owner = uuid4()
    now = datetime.now(UTC)
    _seed_job(db_session_factory, job_id, expires_at=now + timedelta(hours=1))

    first_session = db_session_factory()
    retry_session = db_session_factory()
    duplicate_session = db_session_factory()
    try:
        first_repository = JobRepository(first_session)
        first_repository.acquire_lease(
            job_id,
            owner_token=first_owner,
            now=now,
            lease_expires_at=now + timedelta(minutes=20),
        )
        first_repository.commit()

        retry = JobRepository(retry_session).acquire_lease(
            job_id,
            owner_token=retry_owner,
            previous_owner_token=first_owner,
            now=now + timedelta(seconds=1),
            lease_expires_at=now + timedelta(minutes=20),
        )
        retry_session.commit()

        duplicate = JobRepository(duplicate_session).acquire_lease(
            job_id,
            owner_token=duplicate_retry_owner,
            previous_owner_token=first_owner,
            now=now + timedelta(seconds=2),
            lease_expires_at=now + timedelta(minutes=20),
        )
        duplicate_session.commit()
    finally:
        first_session.close()
        retry_session.close()
        duplicate_session.close()

    assert retry.disposition is JobClaimDisposition.ACQUIRED
    assert duplicate.disposition is JobClaimDisposition.LEASED


def test_non_owner_cannot_transition_or_fail_claimed_job(
    db_session: Session,
) -> None:
    job_id = uuid4()
    owner = uuid4()
    non_owner = uuid4()
    now = datetime.now(UTC)
    _create_job(
        JobRepository(db_session),
        job_id,
        expires_at=now + timedelta(hours=1),
    )
    repository = JobRepository(db_session)
    repository.acquire_lease(
        job_id,
        owner_token=owner,
        now=now,
        lease_expires_at=now + timedelta(minutes=20),
    )
    repository.commit()

    with pytest.raises(JobLeaseLostError):
        repository.transition_claimed(
            job_id,
            owner_token=non_owner,
            expected_status=JobStatus.QUEUED,
            status=JobStatus.UPLOAD_VALIDATED,
            progress=10,
            message="上传校验完成",
            now=now + timedelta(seconds=1),
            lease_expires_at=now + timedelta(minutes=20),
        )
    repository.rollback()

    with pytest.raises(JobLeaseLostError):
        repository.fail_claimed_job(
            job_id,
            owner_token=non_owner,
            expected_status=JobStatus.QUEUED,
            progress=0,
            message="处理失败",
            error_code="pipeline_failed",
            error_message="Processing failed.",
            now=now + timedelta(seconds=1),
        )
    repository.rollback()

    job = repository.get_job(job_id)
    assert job is not None
    assert job.status is JobStatus.QUEUED
    assert [event.status for event in repository.list_events_after(job_id, 0)] == [
        JobStatus.QUEUED
    ]


def test_owner_cas_rejects_status_regression_without_duplicate_event(
    db_session: Session,
) -> None:
    job_id = uuid4()
    owner = uuid4()
    now = datetime.now(UTC)
    _create_job(
        JobRepository(db_session),
        job_id,
        expires_at=now + timedelta(hours=1),
    )
    repository = JobRepository(db_session)
    repository.acquire_lease(
        job_id,
        owner_token=owner,
        now=now,
        lease_expires_at=now + timedelta(minutes=20),
    )
    repository.commit()
    repository.transition_claimed(
        job_id,
        owner_token=owner,
        expected_status=JobStatus.QUEUED,
        status=JobStatus.UPLOAD_VALIDATED,
        progress=10,
        message="上传校验完成",
        now=now + timedelta(seconds=1),
        lease_expires_at=now + timedelta(minutes=20),
    )
    repository.commit()

    with pytest.raises(JobStateConflictError):
        repository.transition_claimed(
            job_id,
            owner_token=owner,
            expected_status=JobStatus.QUEUED,
            status=JobStatus.PARSING,
            progress=25,
            message="开始解析",
            now=now + timedelta(seconds=2),
            lease_expires_at=now + timedelta(minutes=20),
        )
    repository.rollback()

    job = repository.get_job(job_id)
    assert job is not None
    assert job.status is JobStatus.UPLOAD_VALIDATED
    assert [event.status for event in repository.list_events_after(job_id, 0)] == [
        JobStatus.QUEUED,
        JobStatus.UPLOAD_VALIDATED,
    ]


def test_owner_cannot_regress_even_with_matching_current_status(
    db_session: Session,
) -> None:
    job_id = uuid4()
    owner = uuid4()
    now = datetime.now(UTC)
    repository = JobRepository(db_session)
    _create_job(
        repository,
        job_id,
        expires_at=now + timedelta(hours=1),
    )
    repository.acquire_lease(
        job_id,
        owner_token=owner,
        now=now,
        lease_expires_at=now + timedelta(minutes=20),
    )
    repository.commit()
    repository.transition_claimed(
        job_id,
        owner_token=owner,
        expected_status=JobStatus.QUEUED,
        status=JobStatus.UPLOAD_VALIDATED,
        progress=10,
        message="上传校验完成",
        now=now + timedelta(seconds=1),
        lease_expires_at=now + timedelta(minutes=20),
    )
    repository.commit()

    with pytest.raises(ValueError, match="Invalid claimed job transition"):
        repository.transition_claimed(
            job_id,
            owner_token=owner,
            expected_status=JobStatus.UPLOAD_VALIDATED,
            status=JobStatus.QUEUED,
            progress=0,
            message="不允许回退",
            now=now + timedelta(seconds=2),
            lease_expires_at=now + timedelta(minutes=20),
        )
    repository.rollback()

    job = repository.get_job(job_id)
    assert job is not None
    assert job.status is JobStatus.UPLOAD_VALIDATED
    assert len(repository.list_events_after(job_id, 0)) == 2


def test_expiry_skips_job_with_live_processing_lease(
    db_session: Session,
) -> None:
    job_id = uuid4()
    owner = uuid4()
    now = datetime.now(UTC)
    repository = JobRepository(db_session)
    _create_job(repository, job_id, expires_at=now)
    repository.acquire_lease(
        job_id,
        owner_token=owner,
        now=now,
        lease_expires_at=now + timedelta(minutes=20),
    )
    repository.commit()

    expired = repository.expire_jobs_before(now + timedelta(minutes=1))
    repository.commit()

    job = repository.get_job(job_id)
    assert expired == []
    assert job is not None
    assert job.status is JobStatus.QUEUED


def _seed_job(
    session_factory: sessionmaker[Session],
    job_id: UUID,
    *,
    expires_at: datetime,
) -> None:
    session = session_factory()
    try:
        _create_job(JobRepository(session), job_id, expires_at=expires_at)
        session.commit()
    finally:
        session.close()


def _create_job(
    repository: JobRepository,
    job_id: UUID,
    *,
    expires_at: datetime,
) -> None:
    created_at = expires_at - timedelta(hours=1)
    repository.create_job(
        job_id=job_id,
        source_name="sample.txt",
        file_type="txt",
        size_bytes=16,
        storage_key=str(job_id),
        created_at=created_at,
        expires_at=expires_at,
    )


def _load_migration() -> ModuleType:
    assert MIGRATION_PATH.is_file()
    spec = spec_from_file_location("task6_migration_0003", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"unable to load migration: {MIGRATION_PATH}")
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration
