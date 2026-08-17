import logging
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.orm.session import sessionmaker

from alembic import command
from text_verification.checkers.models import CHECK_CATEGORY_ORDER, CheckCategory, CheckScenario
from text_verification.domain.documents import DocumentModel, FileType, TextBlock
from text_verification.domain.issues import Issue, IssueSeverity
from text_verification.domain.jobs import (
    JobEventMetadata,
    JobStatus,
    TerminalJobStateError,
)
from text_verification.infrastructure.repositories import JobRepository

BACKEND_ROOT = Path(__file__).resolve().parents[2]


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
    assert {"scenario", "enabled_categories"} <= {
        column["name"] for column in inspector.get_columns("jobs")
    }
    assert {"ix_job_events_job_sequence"} <= {
        index["name"] for index in inspector.get_indexes("job_events")
    }
    assert "metadata_json" in {
        column["name"] for column in inspector.get_columns("job_events")
    }
    assert {"document_id", "page", "issue_type"} <= {
        column["name"] for column in inspector.get_columns("issues")
    }


def test_migrations_do_not_disable_application_loggers(db_engine: Engine) -> None:
    del db_engine

    assert not logging.getLogger("text_verification.checkers.registry").disabled
    assert not logging.getLogger("text_verification.infrastructure.storage").disabled


def test_upgrade_from_old_0003_adds_job_check_options_and_keeps_repository_round_trip(
    test_database_url: str,
) -> None:
    with migrated_schema(test_database_url) as (engine, alembic_config):
        command.upgrade(alembic_config, "0003_add_issue_roundtrip_fields")
        assert {"scenario", "enabled_categories"}.isdisjoint(
            {column["name"] for column in inspect(engine).get_columns("jobs")}
        )

        seeded_job_id = uuid4()
        seeded_created_at = datetime.now(UTC)
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO jobs (
                        job_id,
                        source_name,
                        file_type,
                        size_bytes,
                        storage_key,
                        status,
                        progress,
                        error_code,
                        error_message,
                        created_at,
                        updated_at,
                        expires_at
                    ) VALUES (
                        :job_id,
                        :source_name,
                        :file_type,
                        :size_bytes,
                        :storage_key,
                        :status,
                        :progress,
                        :error_code,
                        :error_message,
                        :created_at,
                        :updated_at,
                        :expires_at
                    )
                    """
                ),
                {
                    "job_id": seeded_job_id,
                    "source_name": "preexisting.txt",
                    "file_type": FileType.TXT.value,
                    "size_bytes": 16,
                    "storage_key": str(seeded_job_id),
                    "status": JobStatus.QUEUED.value,
                    "progress": 0,
                    "error_code": None,
                    "error_message": None,
                    "created_at": seeded_created_at,
                    "updated_at": seeded_created_at,
                    "expires_at": seeded_created_at + timedelta(hours=1),
                },
            )

        command.upgrade(alembic_config, "head")
        assert {"scenario", "enabled_categories"} <= {
            column["name"] for column in inspect(engine).get_columns("jobs")
        }

        session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
        try:
            repository = JobRepository(session)
            legacy_job = repository.get_job(seeded_job_id)
            job_id = uuid4()
            now = datetime.now(UTC)

            repository.create_job(
                job_id=job_id,
                source_name="analysis.txt",
                file_type=FileType.TXT.value,
                size_bytes=16,
                storage_key=str(job_id),
                created_at=now,
                expires_at=now + timedelta(hours=1),
                scenario=CheckScenario.LEGAL,
                enabled_categories=[CheckCategory.CHARACTER, CheckCategory.SECURITY],
            )
            repository.commit()

            assert legacy_job is not None
            assert legacy_job.scenario == CheckScenario.GENERAL
            assert legacy_job.enabled_categories == list(CHECK_CATEGORY_ORDER)

            stored = repository.get_job(job_id)
            assert stored is not None
            assert stored.scenario == CheckScenario.LEGAL
            assert stored.enabled_categories == [
                CheckCategory.CHARACTER,
                CheckCategory.SECURITY,
            ]
        finally:
            session.close()


def test_upgrade_from_0004_normalizes_legacy_scenarios_without_editing_applied_revision(
    test_database_url: str,
) -> None:
    with migrated_schema(test_database_url) as (engine, alembic_config):
        command.upgrade(alembic_config, "0004_add_job_check_options")
        created_at = datetime.now(UTC)
        legacy_jobs = {
            uuid4(): "education",
            uuid4(): "medical",
        }
        with engine.begin() as connection:
            for job_id, scenario in legacy_jobs.items():
                connection.execute(
                    text(
                        """
                        INSERT INTO jobs (
                            job_id,
                            source_name,
                            file_type,
                            size_bytes,
                            storage_key,
                            status,
                            progress,
                            error_code,
                            error_message,
                            scenario,
                            enabled_categories,
                            created_at,
                            updated_at,
                            expires_at
                        ) VALUES (
                            :job_id,
                            :source_name,
                            :file_type,
                            :size_bytes,
                            :storage_key,
                            :status,
                            :progress,
                            :error_code,
                            :error_message,
                            :scenario,
                            CAST(:enabled_categories AS jsonb),
                            :created_at,
                            :updated_at,
                            :expires_at
                        )
                        """
                    ),
                    {
                        "job_id": job_id,
                        "source_name": f"{scenario}.txt",
                        "file_type": FileType.TXT.value,
                        "size_bytes": 16,
                        "storage_key": str(job_id),
                        "status": JobStatus.COMPLETED.value,
                        "progress": 100,
                        "error_code": None,
                        "error_message": None,
                        "scenario": scenario,
                        "enabled_categories": '["character"]',
                        "created_at": created_at,
                        "updated_at": created_at,
                        "expires_at": created_at + timedelta(hours=1),
                    },
                )

        command.upgrade(alembic_config, "head")
        with engine.connect() as connection:
            stored = dict(
                connection.execute(
                    text(
                        "SELECT source_name, scenario FROM jobs ORDER BY source_name"
                    )
                ).all()
            )

        assert stored == {
            "education.txt": "academic",
            "medical.txt": "technical",
        }


def test_head_downgrades_back_through_0003_before_removing_analysis_tables(
    test_database_url: str,
) -> None:
    with migrated_schema(test_database_url) as (engine, alembic_config):
        command.upgrade(alembic_config, "head")
        assert {"scenario", "enabled_categories"} <= {
            column["name"] for column in inspect(engine).get_columns("jobs")
        }

        command.downgrade(alembic_config, "0003_add_issue_roundtrip_fields")
        assert {"scenario", "enabled_categories"}.isdisjoint(
            {column["name"] for column in inspect(engine).get_columns("jobs")}
        )
        assert {"document_id", "page", "issue_type"} <= {
            column["name"] for column in inspect(engine).get_columns("issues")
        }

        command.downgrade(alembic_config, "0002_create_documents_issues")
        assert {"document_id", "page", "issue_type"}.isdisjoint(
            {column["name"] for column in inspect(engine).get_columns("issues")}
        )

        command.downgrade(alembic_config, "0001_create_jobs_and_events")
        assert {"documents", "document_blocks", "issues", "checker_failures"}.isdisjoint(
            set(inspect(engine).get_table_names())
        )


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
        scenario=CheckScenario.BUSINESS,
        enabled_categories=[CheckCategory.CHARACTER, CheckCategory.SECURITY],
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
    assert job.scenario == CheckScenario.BUSINESS
    assert job.enabled_categories == [CheckCategory.CHARACTER, CheckCategory.SECURITY]
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


def test_repository_persists_checker_progress_metadata_without_status_transition(
    db_session: Session,
) -> None:
    repository = JobRepository(db_session)
    job_id = uuid4()
    now = datetime.now(UTC)
    repository.create_job(
        job_id=job_id,
        source_name="progress.txt",
        file_type="txt",
        size_bytes=32,
        storage_key=str(job_id),
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )
    repository.transition(job_id, JobStatus.UPLOAD_VALIDATED, 10, "上传校验完成")
    repository.transition(job_id, JobStatus.PARSING, 25, "开始解析")

    repository.record_progress(
        job_id,
        progress=60,
        message="检查进度已更新",
        metadata=JobEventMetadata(
            current_category=CheckCategory.CHARACTER,
            completed_categories=[CheckCategory.CHARACTER],
            issue_count=3,
        ),
    )
    repository.commit()

    job = repository.get_job(job_id)
    event = repository.list_events_after(job_id, after_sequence=3)[0]
    assert job is not None
    assert job.status == JobStatus.PARSING
    assert job.progress == 60
    assert event.status == JobStatus.PARSING
    assert event.metadata == JobEventMetadata(
        current_category=CheckCategory.CHARACTER,
        completed_categories=[CheckCategory.CHARACTER],
        issue_count=3,
    )


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


def test_repository_defaults_legacy_job_check_options(db_session: Session) -> None:
    repository = JobRepository(db_session)
    job_id = uuid4()
    now = datetime.now(UTC)

    repository.create_job(
        job_id=job_id,
        source_name="legacy.txt",
        file_type="txt",
        size_bytes=32,
        storage_key=str(job_id),
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )
    repository.commit()

    job = repository.get_job(job_id)

    assert job is not None
    assert job.scenario == CheckScenario.GENERAL
    assert job.enabled_categories == list(CHECK_CATEGORY_ORDER)


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


@contextmanager
def migrated_schema(test_database_url: str) -> Iterator[tuple[Engine, Config]]:
    schema_name = f"test_migration_{uuid4().hex}"
    admin_engine = create_engine(test_database_url, pool_pre_ping=True)
    schema_url = make_url(test_database_url).update_query_dict(
        {"options": f"-csearch_path={schema_name}"}
    ).render_as_string(hide_password=False)
    alembic_config = Config(str(BACKEND_ROOT / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    alembic_config.attributes["database_url"] = schema_url
    engine: Engine | None = None

    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
        engine = create_engine(schema_url, pool_pre_ping=True)
        yield engine, alembic_config
    finally:
        if engine is not None:
            engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
        admin_engine.dispose()


def seed_analysis_job(db_session: Session) -> UUID:
    now = datetime.now(UTC)
    job_id = uuid4()
    repository = JobRepository(db_session)
    repository.create_job(
        job_id=job_id,
        source_name="analysis.txt",
        file_type=FileType.TXT.value,
        size_bytes=16,
        storage_key=str(job_id),
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )
    repository.commit()
    return job_id


def build_analysis_document(block_specs: list[tuple[str, int | None]]) -> DocumentModel:
    blocks = [
        TextBlock(
            block_id=f"p-{index + 1:06d}",
            kind="paragraph",
            text=text,
            page=page,
            paragraph_index=index,
            parent_id=None,
            style={"style_name": "Normal"},
            source_locator={"paragraph_index": index},
        )
        for index, (text, page) in enumerate(block_specs)
    ]
    return DocumentModel(
        document_id=uuid4(),
        file_type=FileType.TXT,
        source_name="analysis.txt",
        version=1,
        blocks=blocks,
        metadata={"language": "zh-CN"},
    )


def build_analysis_issue(
    document: DocumentModel,
    *,
    block_id: str,
    original: str,
    suggestion: str | None,
    start: int,
    end: int,
    page: int | None,
    issue_type: str,
) -> Issue:
    return Issue(
        issue_id=uuid4(),
        document_id=document.document_id,
        block_id=block_id,
        page=page,
        start=start,
        end=end,
        original=original,
        suggestion=suggestion,
        alternatives=[] if suggestion is None else [suggestion],
        type=issue_type,
        severity=IssueSeverity.WARNING,
        layer=CheckCategory.SECURITY.value,
        message="命中规则。",
        rule_id="security-001",
        source="test",
        source_version="1",
        confidence=1.0,
        auto_fixable=suggestion is not None,
        context=original,
    )
