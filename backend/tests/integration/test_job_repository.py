from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect, text
from sqlalchemy.orm import Session
from sqlalchemy.orm.session import sessionmaker

from text_verification.domain.documents import FileType
from text_verification.domain.jobs import JobStatus, TerminalJobStateError
from text_verification.infrastructure.repositories import JobRepository


def test_database_schema_matches_head_migration(
    db_engine: Engine,
    alembic_config: Config,
) -> None:
    migration_head = ScriptDirectory.from_config(alembic_config).get_current_head()
    inspector = inspect(db_engine)

    with db_engine.connect() as connection:
        applied_revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()

    assert applied_revision == migration_head
    assert {"alembic_version", "job_events", "jobs"} <= set(inspector.get_table_names())
    assert {"ix_jobs_expires_at", "ix_jobs_status"} <= {
        index["name"] for index in inspector.get_indexes("jobs")
    }
    assert {"ix_job_events_job_sequence"} <= {
        index["name"] for index in inspector.get_indexes("job_events")
    }


def test_repository_persists_job_and_ordered_events(db_session: Session) -> None:
    repository = JobRepository(db_session)
    job_id = uuid4()
    now = datetime.now(UTC)

    repository.create_job(
        job_id=job_id,
        source_name="example.docx",
        file_type="docx",
        size_bytes=1024,
        storage_key=str(job_id),
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )
    repository.transition(job_id, JobStatus.UPLOAD_VALIDATED, 10, "上传校验完成")
    repository.transition(job_id, JobStatus.PARSING, 25, "开始解析")
    repository.commit()

    job = repository.get_job(job_id)
    events = repository.list_events_after(job_id, after_sequence=0)
    replay = repository.list_events_after(job_id, after_sequence=1)

    assert job is not None
    assert job.status == JobStatus.PARSING
    assert job.file_type == FileType.DOCX
    assert job.error_code is None
    assert job.error_message is None
    assert [(event.sequence, event.status) for event in events] == [
        (1, JobStatus.QUEUED),
        (2, JobStatus.UPLOAD_VALIDATED),
        (3, JobStatus.PARSING),
    ]
    assert [(event.sequence, event.status) for event in replay] == [
        (2, JobStatus.UPLOAD_VALIDATED),
        (3, JobStatus.PARSING),
    ]


def test_repository_expires_jobs_before_cutoff(db_session: Session) -> None:
    repository = JobRepository(db_session)
    job_id = uuid4()
    created_at = datetime.now(UTC)

    repository.create_job(
        job_id=job_id,
        source_name="stale.txt",
        file_type="txt",
        size_bytes=32,
        storage_key=str(job_id),
        created_at=created_at,
        expires_at=created_at,
    )

    first_expired_job_ids = repository.expire_jobs_before(created_at + timedelta(minutes=1))
    repository.commit()
    second_expired_job_ids = repository.expire_jobs_before(created_at + timedelta(minutes=1))
    repository.commit()
    job = repository.get_job(job_id)

    assert first_expired_job_ids == [job_id]
    assert second_expired_job_ids == [job_id]
    assert job is not None
    assert job.status == JobStatus.EXPIRED
    assert [
        (event.sequence, event.status) for event in repository.list_events_after(job_id, 0)
    ] == [
        (1, JobStatus.QUEUED),
        (2, JobStatus.EXPIRED),
    ]


def test_repository_lists_all_persisted_job_ids(db_session: Session) -> None:
    repository = JobRepository(db_session)
    now = datetime.now(UTC)
    job_ids = [uuid4(), uuid4()]
    for job_id in job_ids:
        repository.create_job(
            job_id=job_id,
            source_name=f"{job_id}.txt",
            file_type="txt",
            size_bytes=32,
            storage_key=str(job_id),
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )
    repository.commit()

    assert repository.list_job_ids() == set(job_ids)


def test_transition_rejects_stale_non_terminal_update_after_competing_expiry(
    db_session_factory: sessionmaker[Session],
) -> None:
    job_id = uuid4()
    created_at = datetime.now(UTC)

    seed_session = db_session_factory()
    try:
        repository = JobRepository(seed_session)
        repository.create_job(
            job_id=job_id,
            source_name="stale-race.txt",
            file_type="txt",
            size_bytes=64,
            storage_key=str(job_id),
            created_at=created_at,
            expires_at=created_at,
        )
        repository.commit()
    finally:
        seed_session.close()

    stale_session = db_session_factory()
    expiry_session = db_session_factory()
    try:
        stale_repository = JobRepository(stale_session)
        expiry_repository = JobRepository(expiry_session)

        stale_job = stale_repository.get_job(job_id)
        assert stale_job is not None
        assert stale_job.status == JobStatus.QUEUED

        assert expiry_repository.expire_jobs_before(created_at + timedelta(minutes=1)) == [job_id]
        expiry_repository.commit()

        with pytest.raises(TerminalJobStateError, match="terminal"):
            stale_repository.transition(job_id, JobStatus.UPLOAD_VALIDATED, 10, "上传校验完成")
    finally:
        stale_session.rollback()
        stale_session.close()
        expiry_session.close()

    verification_session = db_session_factory()
    try:
        repository = JobRepository(verification_session)
        job = repository.get_job(job_id)
        events = repository.list_events_after(job_id, 0)
    finally:
        verification_session.close()

    assert job is not None
    assert job.status == JobStatus.EXPIRED
    assert [(event.sequence, event.status) for event in events] == [
        (1, JobStatus.QUEUED),
        (2, JobStatus.EXPIRED),
    ]


def test_transition_serializes_concurrent_updates_without_sequence_gaps(
    db_session_factory: sessionmaker[Session],
) -> None:
    job_id = uuid4()
    now = datetime.now(UTC)

    seed_session = db_session_factory()
    try:
        seed_repository = JobRepository(seed_session)
        seed_repository.create_job(
            job_id=job_id,
            source_name="contention.docx",
            file_type="docx",
            size_bytes=2048,
            storage_key=str(job_id),
            created_at=now,
            expires_at=now + timedelta(hours=24),
        )
        seed_repository.commit()
    finally:
        seed_session.close()

    first_transition_applied = Event()
    second_transition_started = Event()
    second_transition_committed = Event()
    allow_first_commit = Event()

    def first_worker() -> None:
        session = db_session_factory()
        repository = JobRepository(session)
        try:
            session.execute(text("SET lock_timeout = '4s'"))
            repository.transition(job_id, JobStatus.UPLOAD_VALIDATED, 10, "上传校验完成")
            first_transition_applied.set()
            if not allow_first_commit.wait(timeout=2):
                raise TimeoutError("timed out waiting to release the first transition")
            repository.commit()
        except Exception:
            repository.rollback()
            raise
        finally:
            session.close()

    def second_worker() -> None:
        session = db_session_factory()
        repository = JobRepository(session)
        try:
            session.execute(text("SET lock_timeout = '4s'"))
            second_transition_started.set()
            repository.transition(job_id, JobStatus.PARSING, 25, "开始解析")
            repository.commit()
            second_transition_committed.set()
        except Exception:
            repository.rollback()
            raise
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(first_worker)
        assert first_transition_applied.wait(timeout=2)

        second_future = executor.submit(second_worker)
        assert second_transition_started.wait(timeout=1)
        assert not second_transition_committed.wait(timeout=0.2)

        allow_first_commit.set()

        first_future.result(timeout=5)
        second_future.result(timeout=5)

    verification_session = db_session_factory()
    try:
        repository = JobRepository(verification_session)
        job = repository.get_job(job_id)
        events = repository.list_events_after(job_id, after_sequence=0)
    finally:
        verification_session.close()

    assert job is not None
    assert job.status == JobStatus.PARSING
    assert [event.sequence for event in events] == [1, 2, 3]
    assert len({event.sequence for event in events}) == 3
    assert [event.status for event in events] == [
        JobStatus.QUEUED,
        JobStatus.UPLOAD_VALIDATED,
        JobStatus.PARSING,
    ]
