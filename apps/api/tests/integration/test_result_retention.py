from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from sqlalchemy.orm.session import sessionmaker

from text_verification.application import (
    ArtifactPersistenceRequest,
    ArtifactPersistenceService,
)
from text_verification.domain.documents import FileType, TextBlock
from text_verification.domain.issues import Issue, IssueSeverity
from text_verification.domain.jobs import JobStatus
from text_verification.domain.verification import (
    Scenario,
    VerificationAnalysisMode,
    VerificationDegradation,
    VerificationExecutionMode,
    VerificationResult,
    VerificationStatistics,
    VerificationSummary,
)
from text_verification.infrastructure.orm import (
    DocumentRow,
    ExportArtifactRow,
    JobEventRow,
    JobRow,
    ReviewRevisionRow,
    VerificationIssueRow,
    VerificationRunRow,
)
from text_verification.infrastructure.repositories import JobRepository
from text_verification.infrastructure.storage import (
    JobStorage,
    build_artifact_storage_key,
)
from text_verification.infrastructure.verification_repository import (
    JobResultState,
    VerificationRepository,
)


@pytest.fixture
def artifact_storage(tmp_path: Path) -> JobStorage:
    return JobStorage(tmp_path / "storage", max_upload_bytes=1024 * 1024)


def test_expiry_deletes_canonical_aggregate_but_keeps_job_tombstone(
    db_session: Session,
    artifact_storage: JobStorage,
) -> None:
    job_id = uuid4()
    run_id = uuid4()
    revision_id = uuid4()
    now = datetime.now(UTC)
    _seed_completed_aggregate(
        db_session,
        job_id=job_id,
        run_id=run_id,
        revision_id=revision_id,
        expires_at=now,
        artifact_storage=artifact_storage,
    )
    jobs = JobRepository(db_session)
    results = VerificationRepository(db_session)

    expired_ids = jobs.expire_jobs_before(now + timedelta(minutes=1))
    results.delete_results_for_jobs(expired_ids)
    results.commit()

    job = db_session.get(JobRow, job_id)
    assert expired_ids == [job_id]
    assert job is not None
    assert job.status == JobStatus.EXPIRED.value
    assert db_session.scalar(
        select(func.count()).select_from(JobEventRow).where(JobEventRow.job_id == job_id)
    ) == 3
    assert _aggregate_counts(db_session, job_id, run_id, revision_id) == (0, 0, 0, 0, 0)


def test_atomic_result_snapshot_blocks_expiry_until_result_is_materialized(
    db_session_factory: sessionmaker[Session],
    artifact_storage: JobStorage,
) -> None:
    job_id = uuid4()
    run_id = uuid4()
    revision_id = uuid4()
    now = datetime.now(UTC)
    seed_session = db_session_factory()
    try:
        _seed_completed_aggregate(
            seed_session,
            job_id=job_id,
            run_id=run_id,
            revision_id=revision_id,
            expires_at=now,
            artifact_storage=artifact_storage,
        )
    finally:
        seed_session.close()

    snapshot_read = Event()
    allow_reader_release = Event()
    cleanup_started = Event()
    cleanup_finished = Event()

    def reader() -> VerificationResult:
        session = db_session_factory()
        try:
            session.execute(text("SET lock_timeout = '4s'"))
            snapshot = VerificationRepository(session).read_result_snapshot(job_id)
            assert snapshot.state is JobResultState.READY
            assert snapshot.result is not None
            snapshot_read.set()
            if not allow_reader_release.wait(timeout=2):
                raise TimeoutError("timed out waiting to release result snapshot")
            session.rollback()
            return snapshot.result
        finally:
            session.close()

    def cleanup() -> None:
        session = db_session_factory()
        try:
            session.execute(text("SET lock_timeout = '4s'"))
            cleanup_started.set()
            jobs = JobRepository(session)
            results = VerificationRepository(session)
            expired_ids = jobs.expire_jobs_before(now + timedelta(minutes=1))
            results.delete_results_for_jobs(expired_ids)
            results.commit()
            cleanup_finished.set()
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        reader_future = executor.submit(reader)
        assert snapshot_read.wait(timeout=2)
        cleanup_future = executor.submit(cleanup)
        assert cleanup_started.wait(timeout=1)
        assert not cleanup_finished.wait(timeout=0.2)
        allow_reader_release.set()
        materialized = reader_future.result(timeout=5)
        cleanup_future.result(timeout=5)

    verification_session = db_session_factory()
    try:
        snapshot = VerificationRepository(verification_session).read_result_snapshot(job_id)
        verification_session.rollback()
    finally:
        verification_session.close()

    assert materialized.document_id == job_id
    assert snapshot.state is JobResultState.EXPIRED
    assert snapshot.result is None


def test_committed_result_prevents_claimed_failure_in_two_session_race(
    db_session_factory: sessionmaker[Session],
) -> None:
    job_id = uuid4()
    run_id = uuid4()
    owner = uuid4()
    now = datetime.now(UTC)
    seed_session = db_session_factory()
    try:
        jobs = JobRepository(seed_session)
        jobs.create_job(
            job_id=job_id,
            source_name="sample.txt",
            file_type=FileType.TXT,
            size_bytes=16,
            storage_key=str(job_id),
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )
        jobs.acquire_lease(
            job_id,
            owner_token=owner,
            now=now,
            lease_expires_at=now + timedelta(minutes=20),
        )
        jobs.commit()
        _advance_to_checking_english(jobs, job_id, owner, now)
    finally:
        seed_session.close()

    result_saved = Event()
    failure_started = Event()
    failure_finished = Event()
    allow_result_commit = Event()

    def persist_result() -> None:
        session = db_session_factory()
        repository = VerificationRepository(session)
        try:
            session.execute(text("SET lock_timeout = '4s'"))
            repository.save_claimed_result(
                job_id,
                _result(job_id, run_id),
                owner_token=owner,
                expected_status=JobStatus.CHECKING_ENGLISH,
                now=now + timedelta(minutes=1),
            )
            result_saved.set()
            if not allow_result_commit.wait(timeout=2):
                raise TimeoutError("timed out waiting to commit result")
            repository.commit()
        except Exception:
            repository.rollback()
            raise
        finally:
            session.close()

    def persist_failure() -> bool:
        session = db_session_factory()
        repository = JobRepository(session)
        try:
            session.execute(text("SET lock_timeout = '4s'"))
            failure_started.set()
            applied = repository.fail_claimed_job(
                job_id,
                owner_token=owner,
                expected_status=JobStatus.CHECKING_ENGLISH,
                progress=90,
                message="处理失败",
                error_code="pipeline_failed",
                error_message="Processing failed.",
                now=now + timedelta(minutes=1),
            )
            repository.commit()
            return applied
        finally:
            failure_finished.set()
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        result_future = executor.submit(persist_result)
        assert result_saved.wait(timeout=2)
        failure_future = executor.submit(persist_failure)
        assert failure_started.wait(timeout=1)
        assert not failure_finished.wait(timeout=0.2)
        allow_result_commit.set()
        result_future.result(timeout=5)
        failure_applied = failure_future.result(timeout=5)

    verification_session = db_session_factory()
    try:
        job = JobRepository(verification_session).get_job(job_id)
        result = VerificationRepository(verification_session).get_result_for_job(job_id)
    finally:
        verification_session.close()

    assert failure_applied is False
    assert job is not None
    assert job.status is JobStatus.CHECKING_ENGLISH
    assert result is not None


def _seed_completed_aggregate(
    session: Session,
    *,
    job_id: UUID,
    run_id: UUID,
    revision_id: UUID,
    expires_at: datetime,
    artifact_storage: JobStorage,
) -> None:
    created_at = expires_at - timedelta(hours=1)
    jobs = JobRepository(session)
    jobs.create_job(
        job_id=job_id,
        source_name="sample.txt",
        file_type=FileType.TXT,
        size_bytes=16,
        storage_key=str(job_id),
        created_at=created_at,
        expires_at=expires_at,
    )
    jobs.commit()
    results = VerificationRepository(session)
    result = _result(job_id, run_id)
    results.save_result(job_id, result)
    results.save_review_revision(
        review_revision_id=revision_id,
        verification_run_id=run_id,
        source_version=result.source_version,
        revision_number=1,
        text=result.text,
        created_at=created_at,
    )
    results.commit()
    artifact_id = uuid4()
    storage_key = build_artifact_storage_key(job_id, artifact_id, FileType.TXT)
    session_factory = sessionmaker(
        bind=session.get_bind(),
        autoflush=False,
        expire_on_commit=False,
    )
    ArtifactPersistenceService(
        artifact_storage,
        _artifact_repository_factory(session_factory),
    ).persist(
        ArtifactPersistenceRequest(
            job_id=job_id,
            export_artifact_id=artifact_id,
            verification_run_id=run_id,
            review_revision_id=revision_id,
            source_version=result.source_version,
            file_type=FileType.TXT,
            file_name="sample.txt",
            media_type="text/plain",
            storage_key=storage_key,
            data=result.text.encode(),
            created_at=created_at,
        )
    )
    jobs.transition(job_id, JobStatus.COMPLETED, 100, "处理完成")
    jobs.commit()


def _artifact_repository_factory(
    session_factory: sessionmaker[Session],
):
    @contextmanager
    def factory() -> Iterator[VerificationRepository]:
        repository_session = session_factory()
        try:
            yield VerificationRepository(repository_session)
        finally:
            repository_session.close()

    return factory


def _advance_to_checking_english(
    repository: JobRepository,
    job_id: UUID,
    owner: UUID,
    now: datetime,
) -> None:
    transitions = (
        (JobStatus.QUEUED, JobStatus.UPLOAD_VALIDATED, 10, "上传校验完成"),
        (JobStatus.UPLOAD_VALIDATED, JobStatus.PARSING, 25, "开始解析"),
        (JobStatus.PARSING, JobStatus.CHECKING_FORMAT, 50, "正在检查格式"),
        (
            JobStatus.CHECKING_FORMAT,
            JobStatus.CHECKING_SENSITIVE,
            65,
            "正在检查敏感词",
        ),
        (
            JobStatus.CHECKING_SENSITIVE,
            JobStatus.CHECKING_CHINESE,
            80,
            "正在检查中文",
        ),
        (
            JobStatus.CHECKING_CHINESE,
            JobStatus.CHECKING_ENGLISH,
            90,
            "正在检查英文",
        ),
    )
    for index, (expected, target, progress, message) in enumerate(transitions, start=1):
        changed_at = now + timedelta(seconds=index)
        repository.transition_claimed(
            job_id,
            owner_token=owner,
            expected_status=expected,
            status=target,
            progress=progress,
            message=message,
            now=changed_at,
            lease_expires_at=now + timedelta(minutes=20),
        )
        repository.commit()


def _result(job_id: UUID, run_id: UUID) -> VerificationResult:
    text_value = "帐号测试"
    issue = Issue(
        issue_id=uuid4(),
        document_id=job_id,
        verification_run_id=run_id,
        block_id="p-0",
        page=None,
        start=0,
        end=2,
        block_start=0,
        block_end=2,
        original="帐号",
        suggestion="账号",
        alternatives=["账号"],
        type="typo",
        severity=IssueSeverity.WARNING,
        layer="character",
        message="疑似错别字",
        description="疑似错别字",
        rule_id="cn_typo",
        rule_version="1",
        source="test",
        source_version="1",
        confidence=0.8,
        auto_fixable=True,
        context=text_value,
    )
    return VerificationResult(
        verification_run_id=run_id,
        document_id=job_id,
        source_version="sha256:retention",
        source_name="sample.txt",
        file_type=FileType.TXT,
        scenario=Scenario.GENERAL,
        text=text_value,
        blocks=(
            TextBlock(
                block_id="p-0",
                kind="paragraph",
                text=text_value,
                global_start=0,
                global_end=len(text_value),
                block_start=0,
                block_end=len(text_value),
                page=None,
                paragraph_index=0,
                table_index=None,
                row_index=None,
                cell_index=None,
                bbox=None,
                parent_id=None,
                style={},
                source_locator={"paragraph_index": 0},
            ),
        ),
        parser_name="test-parser",
        parser_version="1",
        stats=VerificationStatistics(
            char_count=4,
            char_count_no_space=4,
            line_count=1,
            paragraph_count=1,
            language="zh",
            primary_count=4,
            primary_label="中文字符",
        ),
        issues=(issue,),
        summary=VerificationSummary(
            total=1,
            by_type={"typo": 1},
            by_severity={"warning": 1},
            by_rule={"cn_typo": 1},
            by_layer={"character": 1},
        ),
        execution_mode=VerificationExecutionMode.ASYNCHRONOUS,
        analysis_mode=VerificationAnalysisMode.LOCAL_ONLY,
        dictionary_versions={},
        degradation=VerificationDegradation(),
    )


def _aggregate_counts(
    session: Session,
    job_id: UUID,
    run_id: UUID,
    revision_id: UUID,
) -> tuple[int, int, int, int, int]:
    return (
        int(
            session.scalar(
                select(func.count()).select_from(DocumentRow).where(
                    DocumentRow.job_id == job_id
                )
            )
            or 0
        ),
        int(
            session.scalar(
                select(func.count()).select_from(VerificationRunRow).where(
                    VerificationRunRow.job_id == job_id
                )
            )
            or 0
        ),
        int(
            session.scalar(
                select(func.count()).select_from(VerificationIssueRow).where(
                    VerificationIssueRow.verification_run_id == run_id
                )
            )
            or 0
        ),
        int(
            session.scalar(
                select(func.count()).select_from(ReviewRevisionRow).where(
                    ReviewRevisionRow.review_revision_id == revision_id
                )
            )
            or 0
        ),
        int(
            session.scalar(
                select(func.count()).select_from(ExportArtifactRow).where(
                    ExportArtifactRow.verification_run_id == run_id
                )
            )
            or 0
        ),
    )
