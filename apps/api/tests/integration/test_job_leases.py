from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from threading import Event
from types import ModuleType
from uuid import UUID, uuid4

import pytest
from sqlalchemy import CheckConstraint, Engine, MetaData, Table, inspect, text
from sqlalchemy.orm import Session
from sqlalchemy.orm.session import sessionmaker

from alembic import command
from text_verification.domain.jobs import (
    JobClaimDisposition,
    JobClaimResult,
    JobLeaseLostError,
    JobStateConflictError,
    JobStatus,
)
from text_verification.infrastructure.orm import JobRow
from text_verification.infrastructure.repositories import JobRepository

BACKEND_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = BACKEND_ROOT / "alembic/versions/0003_add_job_leases.py"
FINAL_MIGRATION_PATH = (
    BACKEND_ROOT / "alembic/versions/0004_finalize_verification_pipeline.py"
)


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


def test_job_orm_and_final_migration_define_durable_recovery_metadata() -> None:
    assert {
        "rescue_due_at",
        "rescue_attempts",
        "rescue_last_published_at",
    } <= set(JobRow.__table__.c.keys())
    assert {index.name for index in JobRow.__table__.indexes} >= {
        "ix_jobs_rescue_due_at"
    }
    assert {
        constraint.name
        for constraint in JobRow.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    } >= {"ck_jobs_rescue_attempts"}

    migration = _load_migration(FINAL_MIGRATION_PATH, "final_migration_0004")
    assert migration.revision == "0004_finalize_verification_pipeline"
    assert migration.down_revision == "0003_add_job_leases"


def test_database_schema_contains_durable_recovery_metadata(db_engine: Engine) -> None:
    inspector = inspect(db_engine)
    columns = {column["name"] for column in inspector.get_columns("jobs")}

    assert {
        "rescue_due_at",
        "rescue_attempts",
        "rescue_last_published_at",
    } <= columns
    assert {index["name"] for index in inspector.get_indexes("jobs")} >= {
        "ix_jobs_rescue_due_at"
    }
    assert {constraint["name"] for constraint in inspector.get_check_constraints("jobs")} >= {
        "ck_jobs_rescue_attempts"
    }


def test_upgrade_from_0003_remaps_existing_issue_to_synthesized_block(
    db_engine: Engine,
    alembic_config,
) -> None:
    job_id = uuid4()
    document_id = uuid4()
    run_id = uuid4()
    issue_id = uuid4()
    created_at = datetime.now(UTC)

    try:
        command.downgrade(alembic_config, "0003_add_job_leases")
        metadata = MetaData()
        jobs = Table("jobs", metadata, autoload_with=db_engine)
        documents = Table("documents", metadata, autoload_with=db_engine)
        runs = Table("verification_runs", metadata, autoload_with=db_engine)
        issues = Table("verification_issues", metadata, autoload_with=db_engine)
        with db_engine.begin() as connection:
            connection.execute(
                jobs.insert().values(
                    job_id=job_id,
                    source_name="legacy.txt",
                    file_type="txt",
                    size_bytes=4,
                    storage_key=str(job_id),
                    status="completed",
                    progress=100,
                    created_at=created_at,
                    updated_at=created_at,
                    expires_at=created_at + timedelta(days=1),
                    lease_owner_token=None,
                    lease_expires_at=None,
                )
            )
            connection.execute(
                documents.insert().values(
                    document_id=document_id,
                    job_id=job_id,
                    source_version="sha256:legacy",
                    source_name="legacy.txt",
                    file_type="txt",
                    text="甲帐号乙",
                    created_at=created_at,
                )
            )
            connection.execute(
                runs.insert().values(
                    verification_run_id=run_id,
                    job_id=job_id,
                    document_id=document_id,
                    scenario="general",
                    execution_mode="asynchronous",
                    analysis_mode="local_only",
                    stats_char_count=4,
                    stats_char_count_no_space=4,
                    stats_line_count=1,
                    stats_paragraph_count=1,
                    stats_language="zh",
                    stats_primary_count=4,
                    stats_primary_label="总字数",
                    summary_total=1,
                    summary_by_type={"typo": 1},
                    summary_by_severity={"warning": 1},
                    summary_by_rule={"legacy": 1},
                    summary_by_layer={"character": 1},
                    summary_llm_review=None,
                    dictionary_versions={},
                    degradation_is_degraded=False,
                    degradation_reasons=[],
                    created_at=created_at,
                )
            )
            connection.execute(
                issues.insert().values(
                    verification_run_id=run_id,
                    document_id=document_id,
                    issue_id=issue_id,
                    issue_index=0,
                    block_id="legacy-paragraph-7",
                    page=None,
                    start=1,
                    end=3,
                    block_start=4,
                    block_end=6,
                    original="帐号",
                    suggestion="账号",
                    alternatives=[],
                    type="typo",
                    severity="warning",
                    layer="character",
                    message="建议修正",
                    description="旧数据",
                    rule_id="legacy",
                    rule_version="1",
                    source="legacy",
                    source_version="1",
                    confidence=0.9,
                    auto_fixable=True,
                    context="甲帐号乙",
                    review=None,
                    review_reason=None,
                )
            )

        command.upgrade(alembic_config, "head")

        with db_engine.connect() as connection:
            block = connection.execute(
                text(
                    "SELECT block_id, global_start, global_end, block_start, block_end "
                    "FROM document_blocks WHERE document_id = :document_id"
                ),
                {"document_id": document_id},
            ).one()
            issue = connection.execute(
                text(
                    'SELECT block_id, block_start, block_end, start, "end" '
                    "FROM verification_issues WHERE issue_id = :issue_id"
                ),
                {"issue_id": issue_id},
            ).one()

        assert block == ("file-0", 0, 4, 0, 4)
        assert issue == ("file-0", 1, 3, 1, 3)

        command.downgrade(alembic_config, "0003_add_job_leases")
        assert "document_blocks" not in inspect(db_engine).get_table_names()
        with db_engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT block_id, block_start, block_end "
                    "FROM verification_issues WHERE issue_id = :issue_id"
                ),
                {"issue_id": issue_id},
            ).one() == ("file-0", 1, 3)
    finally:
        command.upgrade(alembic_config, "head")
        with db_engine.begin() as connection:
            connection.execute(
                text(
                    "TRUNCATE TABLE "
                    "export_artifacts, review_revisions, verification_issues, "
                    "verification_runs, document_blocks, documents, job_events, jobs "
                    "RESTART IDENTITY CASCADE"
                )
            )


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
    assert duplicate.lease_expires_at == now + timedelta(minutes=20)
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


def test_retention_expired_unleased_job_rejects_fresh_delivery(
    db_session: Session,
) -> None:
    job_id = uuid4()
    now = datetime.now(UTC)
    repository = JobRepository(db_session)
    _create_job(repository, job_id, expires_at=now)
    repository.commit()

    claim = repository.acquire_lease(
        job_id,
        owner_token=uuid4(),
        now=now,
        lease_expires_at=now + timedelta(minutes=20),
    )
    repository.commit()

    row = db_session.get(JobRow, job_id)
    assert claim.disposition.value == "retention_expired"
    assert row is not None
    assert row.lease_owner_token is None
    assert row.lease_expires_at is None


def test_live_predecessor_retry_can_rotate_after_retention_expiry(
    db_session: Session,
) -> None:
    job_id = uuid4()
    first_owner = uuid4()
    retry_owner = uuid4()
    now = datetime.now(UTC)
    repository = JobRepository(db_session)
    _create_job(repository, job_id, expires_at=now - timedelta(seconds=30))
    repository.acquire_lease(
        job_id,
        owner_token=first_owner,
        now=now - timedelta(minutes=1),
        lease_expires_at=now + timedelta(minutes=20),
    )
    repository.commit()

    claim = repository.acquire_lease(
        job_id,
        owner_token=retry_owner,
        previous_owner_token=first_owner,
        now=now,
        lease_expires_at=now + timedelta(minutes=20),
    )
    repository.commit()

    row = db_session.get(JobRow, job_id)
    assert claim.disposition is JobClaimDisposition.ACQUIRED
    assert row is not None
    assert row.lease_owner_token == retry_owner


def test_expiry_and_fresh_delivery_race_never_starts_retention_expired_job(
    db_session_factory: sessionmaker[Session],
) -> None:
    job_id = uuid4()
    now = datetime.now(UTC)
    _seed_job(db_session_factory, job_id, expires_at=now)
    expiry_locked = Event()
    allow_expiry_commit = Event()
    claim_started = Event()
    claim_finished = Event()

    def expire() -> list[UUID]:
        session = db_session_factory()
        try:
            session.execute(text("SET lock_timeout = '4s'"))
            repository = JobRepository(session)
            expired = repository.expire_jobs_before(now)
            expiry_locked.set()
            if not allow_expiry_commit.wait(timeout=2):
                raise TimeoutError("timed out waiting to commit expiry")
            repository.commit()
            return expired
        finally:
            session.close()

    def claim() -> JobClaimResult:
        session = db_session_factory()
        try:
            session.execute(text("SET lock_timeout = '4s'"))
            claim_started.set()
            result = JobRepository(session).acquire_lease(
                job_id,
                owner_token=uuid4(),
                now=now,
                lease_expires_at=now + timedelta(minutes=20),
            )
            session.commit()
            return result
        finally:
            claim_finished.set()
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        expiry_future = executor.submit(expire)
        assert expiry_locked.wait(timeout=2)
        claim_future = executor.submit(claim)
        assert claim_started.wait(timeout=1)
        assert not claim_finished.wait(timeout=0.2)
        allow_expiry_commit.set()
        assert expiry_future.result(timeout=5) == [job_id]
        claim_result = claim_future.result(timeout=5)

    verification_session = db_session_factory()
    try:
        job = JobRepository(verification_session).get_job(job_id)
    finally:
        verification_session.close()

    assert claim_result.disposition is JobClaimDisposition.TERMINAL
    assert job is not None
    assert job.status is JobStatus.EXPIRED


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


def test_due_recovery_scan_claims_only_expired_or_unleased_nonterminal_jobs(
    db_session: Session,
) -> None:
    now = datetime.now(UTC)
    expired_lease_job = uuid4()
    unleased_job = uuid4()
    live_lease_job = uuid4()
    retention_expired_job = uuid4()
    terminal_job = uuid4()
    repository = JobRepository(db_session)
    for job_id in (
        expired_lease_job,
        unleased_job,
        live_lease_job,
        terminal_job,
    ):
        _create_job(repository, job_id, expires_at=now + timedelta(hours=1))
    _create_job(repository, retention_expired_job, expires_at=now)
    repository.commit()
    repository.acquire_lease(
        expired_lease_job,
        owner_token=uuid4(),
        now=now - timedelta(minutes=2),
        lease_expires_at=now - timedelta(minutes=1),
    )
    repository.acquire_lease(
        live_lease_job,
        owner_token=uuid4(),
        now=now,
        lease_expires_at=now + timedelta(minutes=20),
    )
    repository.transition(terminal_job, JobStatus.FAILED, 0, "处理失败")
    repository.commit()
    recovery_now = now + timedelta(minutes=3)
    publication_due_at = recovery_now + timedelta(minutes=2)

    claims = repository.claim_due_recoveries(
        now=recovery_now,
        publication_due_at=publication_due_at,
        limit=100,
    )
    repository.commit()

    assert {claim.job.job_id for claim in claims if claim.job is not None} == {
        expired_lease_job,
        unleased_job,
    }
    for job_id in (expired_lease_job, unleased_job):
        row = db_session.get(JobRow, job_id)
        assert row is not None
        assert row.rescue_due_at == publication_due_at
        assert row.rescue_attempts == 1


def test_due_recovery_scan_distinguishes_initial_dispatch_and_expired_lease(
    db_session: Session,
) -> None:
    now = datetime.now(UTC)
    initial_job = uuid4()
    expired_lease_job = uuid4()
    repository = JobRepository(db_session)
    _create_job(repository, initial_job, expires_at=now + timedelta(hours=1))
    _create_job(repository, expired_lease_job, expires_at=now + timedelta(hours=1))
    repository.commit()
    repository.acquire_lease(
        expired_lease_job,
        owner_token=uuid4(),
        now=now,
        lease_expires_at=now + timedelta(seconds=1),
    )
    repository.commit()
    publication_time = now + timedelta(minutes=2)
    publication_due_at = publication_time + timedelta(minutes=2)

    claims = repository.claim_due_recoveries(
        now=publication_time,
        publication_due_at=publication_due_at,
        limit=100,
    )
    repository.commit()

    claims_by_job = {
        claim.job.job_id: claim
        for claim in claims
        if claim.job is not None
    }
    assert claims_by_job[initial_job].kind.value == "initial_dispatch"
    assert claims_by_job[expired_lease_job].kind.value == "expired_lease"
    assert {claim.attempt for claim in claims} == {1}
    for job_id in (initial_job, expired_lease_job):
        row = db_session.get(JobRow, job_id)
        assert row is not None
        assert row.lease_owner_token is None or row.lease_expires_at <= publication_time
        assert row.rescue_due_at == publication_due_at
        assert row.rescue_attempts == 1


def test_concurrent_due_recovery_scans_skip_already_claimed_rows(
    db_session_factory: sessionmaker[Session],
) -> None:
    now = datetime.now(UTC)
    recovery_now = now + timedelta(minutes=2)
    publication_due_at = recovery_now + timedelta(minutes=2)
    job_ids = [uuid4(), uuid4()]
    for job_id in job_ids:
        _seed_job(
            db_session_factory,
            job_id,
            expires_at=now + timedelta(hours=1),
        )

    first_session = db_session_factory()
    second_session = db_session_factory()
    try:
        first_claims = JobRepository(first_session).claim_due_recoveries(
            now=recovery_now,
            publication_due_at=publication_due_at,
            limit=100,
        )
        second_claims = JobRepository(second_session).claim_due_recoveries(
            now=recovery_now,
            publication_due_at=publication_due_at,
            limit=100,
        )
        first_session.commit()
        second_session.commit()
    finally:
        first_session.close()
        second_session.close()

    assert {claim.job.job_id for claim in first_claims if claim.job is not None} == set(
        job_ids
    )
    assert second_claims == []


def test_confirmed_recovery_is_suppressed_until_worker_claim_resets_it(
    db_session: Session,
) -> None:
    now = datetime.now(UTC)
    job_id = uuid4()
    repository = JobRepository(db_session)
    _create_job(repository, job_id, expires_at=now + timedelta(hours=4))
    repository.commit()
    recovery_now = now + timedelta(minutes=2)
    publication_due_at = recovery_now + timedelta(minutes=2)

    claim = repository.claim_due_recoveries(
        now=recovery_now,
        publication_due_at=publication_due_at,
        limit=1,
    )[0]
    repository.commit()
    assert repository.mark_recovery_published(
        job_id,
        attempt=claim.attempt,
        published_at=recovery_now,
    )
    repository.commit()

    assert repository.claim_due_recoveries(
        now=publication_due_at + timedelta(hours=1),
        publication_due_at=publication_due_at + timedelta(hours=1, minutes=2),
        limit=1,
    ) == []
    owner = uuid4()
    acquired_at = recovery_now + timedelta(seconds=1)
    acquired = repository.acquire_lease(
        job_id,
        owner_token=owner,
        now=acquired_at,
        lease_expires_at=acquired_at + timedelta(minutes=5),
    )
    repository.commit()
    assert acquired.disposition is JobClaimDisposition.ACQUIRED

    next_recovery_at = acquired_at + timedelta(minutes=5)
    next_claims = repository.claim_due_recoveries(
        now=next_recovery_at,
        publication_due_at=next_recovery_at + timedelta(minutes=2),
        limit=1,
    )

    assert [claim.job.job_id for claim in next_claims] == [job_id]


def test_stale_publish_confirmation_cannot_suppress_new_worker_generation(
    db_session_factory: sessionmaker[Session],
) -> None:
    now = datetime.now(UTC)
    recovery_now = now + timedelta(minutes=2)
    job_id = uuid4()
    _seed_job(
        db_session_factory,
        job_id,
        expires_at=now + timedelta(hours=1),
    )

    beat_session = db_session_factory()
    worker_session = db_session_factory()
    try:
        beat_repository = JobRepository(beat_session)
        stale_claim = beat_repository.claim_due_recoveries(
            now=recovery_now,
            publication_due_at=recovery_now + timedelta(minutes=2),
            limit=1,
        )[0]
        beat_repository.commit()

        worker_repository = JobRepository(worker_session)
        acquired = worker_repository.acquire_lease(
            job_id,
            owner_token=uuid4(),
            now=recovery_now + timedelta(seconds=1),
            lease_expires_at=recovery_now + timedelta(minutes=5),
        )
        worker_repository.commit()

        assert acquired.disposition is JobClaimDisposition.ACQUIRED
        assert not beat_repository.mark_recovery_published(
            job_id,
            attempt=stale_claim.attempt,
            published_at=recovery_now + timedelta(seconds=2),
        )
        beat_repository.commit()
    finally:
        beat_session.close()
        worker_session.close()

    verification_session = db_session_factory()
    try:
        row = verification_session.get(JobRow, job_id)
        assert row is not None
        assert row.rescue_last_published_at is None
    finally:
        verification_session.close()


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


def _load_migration(
    path: Path = MIGRATION_PATH,
    module_name: str = "task6_migration_0003",
) -> ModuleType:
    assert path.is_file()
    spec = spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"unable to load migration: {path}")
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration
