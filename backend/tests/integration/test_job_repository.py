from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.orm import Session

from text_verification.domain.documents import FileType
from text_verification.domain.jobs import JobStatus
from text_verification.infrastructure.repositories import JobRepository


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

    expired_job_ids = repository.expire_jobs_before(created_at + timedelta(minutes=1))
    repository.commit()
    job = repository.get_job(job_id)

    assert expired_job_ids == [job_id]
    assert job is not None
    assert job.status == JobStatus.EXPIRED
    assert [
        (event.sequence, event.status) for event in repository.list_events_after(job_id, 0)
    ] == [
        (1, JobStatus.QUEUED),
        (2, JobStatus.EXPIRED),
    ]
    assert repository.expire_jobs_before(created_at + timedelta(minutes=1)) == []
