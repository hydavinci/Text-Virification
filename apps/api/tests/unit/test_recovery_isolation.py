from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import JSON, MetaData, create_engine, select
from sqlalchemy.orm import Session

from text_verification.domain.jobs import JobStatus
from text_verification.domain.verification import decode_verification_options
from text_verification.infrastructure.orm import JobEventRow, JobRow
from text_verification.infrastructure.repositories import JobRepository


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    metadata = MetaData()
    jobs = JobRow.__table__.to_metadata(metadata)
    jobs.c.verification_options.type = JSON()
    jobs.c.verification_options.server_default = None
    JobEventRow.__table__.to_metadata(metadata)
    metadata.create_all(engine)
    with Session(engine, expire_on_commit=False, autoflush=False) as session:
        yield session
    engine.dispose()


def create_job(session, now):
    job_id = uuid4()
    JobRepository(session).create_job(
        job_id=job_id, source_name="source.txt", file_type="txt", size_bytes=1,
        storage_key=str(job_id), created_at=now - timedelta(minutes=3),
        expires_at=now + timedelta(hours=1),
    )
    session.commit()
    return job_id


def test_malformed_options_are_quarantined_without_poisoning_healthy_claims(session):
    now = datetime.now()
    healthy = create_job(session, now)
    malformed = create_job(session, now)
    row = session.get(JobRow, malformed)
    row.verification_options = {"unknown_future_setting": True}
    row.lease_owner_token = uuid4()
    row.lease_expires_at = now - timedelta(seconds=1)
    session.commit()
    repository = JobRepository(session)
    claims = repository.claim_due_recoveries(
        now=now, publication_due_at=now + timedelta(minutes=2), limit=100,
    )
    repository.commit()

    assert [claim.job.job_id for claim in claims] == [healthy]
    session.expire_all()
    row = session.get(JobRow, malformed)
    assert row.status == JobStatus.FAILED.value
    assert row.error_code == "invalid_persisted_job"
    assert row.error_stage == "validation"
    assert row.error_retryable is False
    assert row.lease_owner_token is None
    assert row.lease_expires_at is None
    assert row.storage_key == str(malformed)
    assert row.verification_options == {"unknown_future_setting": True}
    with pytest.raises(ValidationError):
        decode_verification_options(row.verification_options)
    events = session.scalars(
        select(JobEventRow).where(JobEventRow.job_id == malformed)
        .order_by(JobEventRow.sequence)
    ).all()
    assert [event.status for event in events] == ["queued", "failed"]
    assert "unknown_future_setting" not in events[-1].message


def test_published_unclaimed_recovery_retries_only_after_deadline_and_fences_old_ack(session):
    now = datetime.now()
    job_id = create_job(session, now)
    repository = JobRepository(session)
    deadline = now + timedelta(minutes=2)
    first = repository.claim_due_recoveries(now=now, publication_due_at=deadline, limit=1)[0]
    assert repository.mark_recovery_published(job_id, attempt=first.attempt, published_at=now)
    repository.commit()
    assert repository.claim_due_recoveries(
        now=deadline - timedelta(seconds=1),
        publication_due_at=deadline + timedelta(minutes=2), limit=1,
    ) == []
    retry = repository.claim_due_recoveries(
        now=deadline, publication_due_at=deadline + timedelta(minutes=2), limit=1,
    )
    assert len(retry) == 1
    assert retry[0].attempt == first.attempt + 1
    assert not repository.mark_recovery_published(
        job_id, attempt=first.attempt, published_at=deadline,
    )
    assert repository.mark_recovery_published(
        job_id, attempt=retry[0].attempt, published_at=deadline,
    )


@pytest.mark.parametrize("excluded", ["live_lease", "terminal", "retention_expired"])
def test_recovery_does_not_quarantine_or_republish_ineligible_rows(session, excluded):
    now = datetime.now()
    job_id = create_job(session, now)
    row = session.get(JobRow, job_id)
    row.verification_options = {"unknown_future_setting": True}
    row.rescue_last_published_at = now - timedelta(minutes=3)
    if excluded == "live_lease":
        row.lease_owner_token = uuid4()
        row.lease_expires_at = now + timedelta(minutes=1)
    elif excluded == "terminal":
        row.status = "completed"
    else:
        row.expires_at = now
    session.commit()
    owner = row.lease_owner_token
    original_status = row.status
    repository = JobRepository(session)
    assert repository.claim_due_recoveries(
        now=now, publication_due_at=now + timedelta(minutes=2), limit=1,
    ) == []
    repository.commit()
    session.refresh(row)
    assert row.status == original_status
    assert row.lease_owner_token == owner
    assert row.rescue_attempts == 0


def test_lease_acquisition_refreshes_already_loaded_owner(session):
    now = datetime.now()
    job_id = create_job(session, now)
    row = session.get(JobRow, job_id)
    first_owner = uuid4()
    next_owner = uuid4()
    repository = JobRepository(session)
    repository.acquire_lease(
        job_id, owner_token=first_owner, now=now,
        lease_expires_at=now + timedelta(minutes=20),
    )
    repository.commit()
    assert row.lease_owner_token == first_owner
    repository.acquire_lease(
        job_id, owner_token=next_owner, previous_owner_token=first_owner,
        now=now + timedelta(seconds=1), lease_expires_at=now + timedelta(minutes=20),
    )
    repository.commit()
    assert row.lease_owner_token == next_owner
