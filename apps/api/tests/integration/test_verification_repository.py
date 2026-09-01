from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import UUID

import pytest
from sqlalchemy import Engine, Text, inspect, select, text
from sqlalchemy.engine.reflection import Inspector
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.session import sessionmaker

from text_verification.domain.documents import FileType, TextBlock
from text_verification.domain.issues import Issue, IssueSeverity
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
    Base,
    DocumentRow,
    ExportArtifactRow,
    ReviewRevisionRow,
    VerificationIssueRow,
    VerificationRunRow,
)
from text_verification.infrastructure.repositories import JobRepository
from text_verification.infrastructure.verification_repository import (
    VerificationRepository,
    _map_result_to_rows,
    _map_rows_to_result,
)

JOB_ID = UUID("10000000-0000-0000-0000-000000000001")
DOCUMENT_ID = UUID("20000000-0000-0000-0000-000000000002")
RUN_ID = UUID("30000000-0000-0000-0000-000000000003")
ISSUE_ID = UUID("40000000-0000-0000-0000-000000000004")
REVISION_ID = UUID("50000000-0000-0000-0000-000000000005")
ARTIFACT_ID = UUID("60000000-0000-0000-0000-000000000006")
SECOND_JOB_ID = UUID("10000000-0000-0000-0000-000000000011")
SECOND_DOCUMENT_ID = UUID("20000000-0000-0000-0000-000000000012")
SECOND_RUN_ID = UUID("30000000-0000-0000-0000-000000000013")
SECOND_ISSUE_ID = UUID("40000000-0000-0000-0000-000000000014")
SECOND_REVISION_ID = UUID("50000000-0000-0000-0000-000000000015")
SECOND_ARTIFACT_ID = UUID("60000000-0000-0000-0000-000000000016")
CREATED_AT = datetime(2026, 8, 31, 7, 0, tzinfo=UTC)


def test_result_row_mapping_round_trips_every_canonical_field_without_database() -> None:
    result = _result()

    document_row, run_row = _map_result_to_rows(JOB_ID, result, created_at=CREATED_AT)

    assert _map_rows_to_result(document_row, run_row) == result
    assert run_row.issues[0].issue_id == ISSUE_ID
    assert run_row.dictionary_versions == {
        "chinese_terms": "sha256:terms-v4",
        "sensitive_words": "sha256:sensitive-v2",
    }
    assert run_row.degradation_reasons == ["llm_review_failed", "provider_timeout"]


def test_result_row_mapping_round_trips_nested_document_blocks_exactly() -> None:
    result = _structured_result()

    document_row, run_row = _map_result_to_rows(JOB_ID, result, created_at=CREATED_AT)
    loaded = _map_rows_to_result(document_row, run_row)

    assert document_row.parser_name == "structured-parser"
    assert document_row.parser_version == "7.2"
    assert [row.block_index for row in document_row.blocks] == [0, 1, 2]
    assert [row.block_id for row in document_row.blocks] == [
        "heading-0",
        "body-0",
        "table-cell-0",
    ]
    assert document_row.blocks[2].page == 2
    assert document_row.blocks[2].paragraph_index == 4
    assert document_row.blocks[2].table_index == 1
    assert document_row.blocks[2].row_index == 2
    assert document_row.blocks[2].cell_index == 3
    assert document_row.blocks[2].parent_id == "body-0"
    assert document_row.blocks[2].bbox == [10.5, 20.5, 30.5, 40.5]
    assert document_row.blocks[2].style == {
        "font": {"family": "Noto Sans", "bold": True},
    }
    assert document_row.blocks[2].source_locator == {
        "page": 2,
        "paragraph_index": 4,
        "table_index": 1,
        "row_index": 2,
        "cell_index": 3,
        "source": "table",
    }
    assert loaded == result
    assert loaded.blocks == result.blocks


def test_result_row_mapping_uses_canonical_json_review_metadata() -> None:
    summary = VerificationSummary.model_validate(
        {
            "total": 1,
            "by_type": {"typo": 1},
            "by_severity": {"warning": 1},
            "by_rule": {"cn_typo_account": 1},
            "by_layer": {"character": 1},
            "llm_review": {"batches": ({"issue_ids": ("first", "second")},)},
        }
    )
    result = _result().model_copy(update={"summary": summary})

    document_row, run_row = _map_result_to_rows(JOB_ID, result, created_at=CREATED_AT)

    assert run_row.summary_llm_review == {
        "batches": [{"issue_ids": ["first", "second"]}]
    }
    assert _map_rows_to_result(document_row, run_row) == result


@pytest.mark.parametrize(
    "column",
    [
        DocumentRow.__table__.c.source_version,
        DocumentRow.__table__.c.source_name,
        VerificationRunRow.__table__.c.stats_primary_label,
        VerificationIssueRow.__table__.c.block_id,
        VerificationIssueRow.__table__.c.type,
        VerificationIssueRow.__table__.c.layer,
        VerificationIssueRow.__table__.c.rule_id,
        VerificationIssueRow.__table__.c.rule_version,
        VerificationIssueRow.__table__.c.source,
        VerificationIssueRow.__table__.c.source_version,
        VerificationIssueRow.__table__.c.review,
        ReviewRevisionRow.__table__.c.source_version,
        ExportArtifactRow.__table__.c.source_version,
        ExportArtifactRow.__table__.c.file_name,
        ExportArtifactRow.__table__.c.media_type,
        ExportArtifactRow.__table__.c.storage_key,
    ],
    ids=lambda column: f"{column.table.name}.{column.name}",
)
def test_unbounded_domain_strings_use_unbounded_database_text(column: object) -> None:
    assert isinstance(column.type, Text)  # type: ignore[attr-defined]


def test_orm_metadata_enforces_cross_owner_relationships() -> None:
    assert (
        ("document_id", "job_id"),
        ("documents.document_id", "documents.job_id"),
        "CASCADE",
    ) in _metadata_foreign_keys(VerificationRunRow)
    assert (
        ("verification_run_id", "document_id"),
        (
            "verification_runs.verification_run_id",
            "verification_runs.document_id",
        ),
        "CASCADE",
    ) in _metadata_foreign_keys(VerificationIssueRow)
    assert (
        ("verification_run_id", "document_id"),
        (
            "verification_runs.verification_run_id",
            "verification_runs.document_id",
        ),
        "CASCADE",
    ) in _metadata_foreign_keys(ReviewRevisionRow)
    assert (
        ("document_id", "source_version"),
        ("documents.document_id", "documents.source_version"),
        "CASCADE",
    ) in _metadata_foreign_keys(ReviewRevisionRow)
    assert (
        ("review_revision_id", "verification_run_id"),
        (
            "review_revisions.review_revision_id",
            "review_revisions.verification_run_id",
        ),
        "CASCADE",
    ) in _metadata_foreign_keys(ExportArtifactRow)

    document_blocks = Base.metadata.tables["document_blocks"]
    assert {"parser_name", "parser_version"} <= set(DocumentRow.__table__.c.keys())
    assert {
        "document_id",
        "block_index",
        "block_id",
        "kind",
        "text",
        "global_start",
        "global_end",
        "block_start",
        "block_end",
        "page",
        "paragraph_index",
        "table_index",
        "row_index",
        "cell_index",
        "bbox",
        "parent_id",
        "style",
        "source_locator",
    } <= set(document_blocks.c.keys())
    assert {
        constraint.name for constraint in document_blocks.constraints
    } >= {
        "uq_document_blocks_identity",
        "uq_document_blocks_order",
        "fk_document_blocks_document",
    }


def test_database_schema_contains_normalized_verification_tables(db_engine: Engine) -> None:
    inspector = inspect(db_engine)
    table_names = set(inspector.get_table_names())

    assert {
        "documents",
        "document_blocks",
        "verification_runs",
        "verification_issues",
        "review_revisions",
        "export_artifacts",
    } <= table_names
    assert {
        "uq_documents_job",
        "uq_documents_identity",
        "uq_documents_document_job",
    } <= _unique_names(inspector, "documents")
    assert {
        "uq_document_blocks_identity",
        "uq_document_blocks_order",
    } <= _unique_names(inspector, "document_blocks")
    assert {
        "uq_verification_runs_job",
        "uq_verification_runs_run_document",
    } <= _unique_names(inspector, "verification_runs")
    assert {
        "uq_verification_issues_run_issue",
        "uq_verification_issues_run_index",
    } <= _unique_names(
        inspector, "verification_issues"
    )
    assert {
        "uq_review_revisions_run_number",
        "uq_review_revisions_revision_run",
    } <= _unique_names(inspector, "review_revisions")
    assert {"uq_export_artifacts_storage_key"} <= _unique_names(
        inspector, "export_artifacts"
    )
    assert ("jobs", ("job_id",), ("job_id",), "CASCADE") in _foreign_keys(
        inspector, "documents"
    )
    assert (
        "documents",
        ("document_id",),
        ("document_id",),
        "CASCADE",
    ) in _foreign_keys(inspector, "document_blocks")
    assert ("jobs", ("job_id",), ("job_id",), "CASCADE") in _foreign_keys(
        inspector, "verification_runs"
    )
    assert (
        "documents",
        ("document_id", "job_id"),
        ("document_id", "job_id"),
        "CASCADE",
    ) in _foreign_keys(inspector, "verification_runs")
    assert (
        "verification_runs",
        ("verification_run_id", "document_id"),
        ("verification_run_id", "document_id"),
        "CASCADE",
    ) in _foreign_keys(inspector, "verification_issues")
    assert (
        "verification_runs",
        ("verification_run_id", "document_id"),
        ("verification_run_id", "document_id"),
        "CASCADE",
    ) in _foreign_keys(inspector, "review_revisions")
    assert (
        "documents",
        ("document_id", "source_version"),
        ("document_id", "source_version"),
        "CASCADE",
    ) in _foreign_keys(inspector, "review_revisions")
    assert (
        "verification_runs",
        ("verification_run_id",),
        ("verification_run_id",),
        "CASCADE",
    ) in _foreign_keys(inspector, "export_artifacts")
    assert (
        "review_revisions",
        ("review_revision_id", "verification_run_id"),
        ("review_revision_id", "verification_run_id"),
        "CASCADE",
    ) in _foreign_keys(inspector, "export_artifacts")


def test_save_and_load_verification_result_round_trips_canonical_data(
    db_session: Session,
) -> None:
    _create_job(db_session)
    repository = VerificationRepository(db_session)
    result = _result()

    repository.save_result(JOB_ID, result)
    repository.commit()
    db_session.expunge_all()

    loaded = repository.get_result_for_job(JOB_ID)

    assert loaded == result
    assert loaded is not None
    assert loaded.issues[0].issue_id == result.issues[0].issue_id
    assert loaded.issues[0].start == 0
    assert loaded.issues[0].end == 2
    assert loaded.issues[0].block_start == 4
    assert loaded.issues[0].block_end == 6
    assert loaded.dictionary_versions == result.dictionary_versions
    assert loaded.degradation == result.degradation
    assert loaded.summary == result.summary
    assert loaded.stats == result.stats


def test_save_and_load_round_trips_full_structured_document(
    db_session: Session,
) -> None:
    _create_job(db_session)
    repository = VerificationRepository(db_session)
    result = _structured_result()

    repository.save_result(JOB_ID, result)
    repository.commit()
    db_session.expunge_all()

    loaded = repository.get_result_for_job(JOB_ID)

    assert loaded == result
    assert loaded is not None
    assert loaded.parser_name == "structured-parser"
    assert loaded.parser_version == "7.2"
    assert [block.block_id for block in loaded.blocks] == [
        "heading-0",
        "body-0",
        "table-cell-0",
    ]
    assert loaded.blocks[2].bbox == (10.5, 20.5, 30.5, 40.5)
    assert loaded.blocks[2].source_locator["source"] == "table"


def test_save_result_is_idempotent_for_same_job_and_run(db_session: Session) -> None:
    _create_job(db_session)
    repository = VerificationRepository(db_session)
    result = _result()

    repository.save_result(JOB_ID, result)
    repository.commit()
    repository.save_result(JOB_ID, result)
    repository.commit()

    assert repository.get_result_for_job(JOB_ID) == result


@pytest.mark.parametrize(
    ("field_name", "replacement", "message"),
    [
        ("source_name", "different.docx", "source name"),
        ("file_type", FileType.PDF, "file type"),
    ],
)
def test_save_result_rejects_job_source_metadata_mismatch(
    db_session: Session,
    field_name: str,
    replacement: object,
    message: str,
) -> None:
    _create_job(db_session)
    result = _result().model_copy(update={field_name: replacement})

    with pytest.raises(ValueError, match=message):
        VerificationRepository(db_session).save_result(JOB_ID, result)


def test_save_result_translates_conflicting_global_identity_to_value_error(
    db_session: Session,
) -> None:
    _create_job(db_session)
    _create_job(db_session, job_id=SECOND_JOB_ID)
    repository = VerificationRepository(db_session)
    result = _result()
    repository.save_result(JOB_ID, result)
    repository.commit()

    with pytest.raises(ValueError, match="conflicts"):
        repository.save_result(SECOND_JOB_ID, result)


def test_save_review_revision_and_export_artifact_preserves_identity_and_source(
    db_session: Session,
) -> None:
    _create_job(db_session)
    repository = VerificationRepository(db_session)
    repository.save_result(JOB_ID, _result())
    repository.save_review_revision(
        review_revision_id=REVISION_ID,
        verification_run_id=RUN_ID,
        source_version="sha256:source-v7",
        revision_number=1,
        text="账号测试\n第二行",
        created_at=CREATED_AT + timedelta(minutes=1),
    )
    repository.save_export_artifact(
        export_artifact_id=ARTIFACT_ID,
        verification_run_id=RUN_ID,
        review_revision_id=REVISION_ID,
        source_version="sha256:source-v7",
        file_type=FileType.DOCX,
        file_name="sample-reviewed.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        storage_key="exports/60000000-0000-0000-0000-000000000006.docx",
        size_bytes=8192,
        created_at=CREATED_AT + timedelta(minutes=2),
    )
    repository.commit()
    repository.save_review_revision(
        review_revision_id=REVISION_ID,
        verification_run_id=RUN_ID,
        source_version="sha256:source-v7",
        revision_number=1,
        text="账号测试\n第二行",
        created_at=CREATED_AT + timedelta(minutes=1),
    )
    repository.save_export_artifact(
        export_artifact_id=ARTIFACT_ID,
        verification_run_id=RUN_ID,
        review_revision_id=REVISION_ID,
        source_version="sha256:source-v7",
        file_type=FileType.DOCX,
        file_name="sample-reviewed.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        storage_key="exports/60000000-0000-0000-0000-000000000006.docx",
        size_bytes=8192,
        created_at=CREATED_AT + timedelta(minutes=2),
    )
    repository.commit()

    revision = db_session.scalar(
        select(ReviewRevisionRow).where(
            ReviewRevisionRow.review_revision_id == REVISION_ID
        )
    )
    artifact = db_session.scalar(
        select(ExportArtifactRow).where(ExportArtifactRow.export_artifact_id == ARTIFACT_ID)
    )

    assert revision is not None
    assert revision.verification_run_id == RUN_ID
    assert revision.document_id == DOCUMENT_ID
    assert revision.source_version == "sha256:source-v7"
    assert revision.revision_number == 1
    assert revision.text == "账号测试\n第二行"
    assert artifact is not None
    assert artifact.verification_run_id == RUN_ID
    assert artifact.review_revision_id == REVISION_ID
    assert artifact.source_version == "sha256:source-v7"
    assert artifact.file_type == FileType.DOCX.value
    assert artifact.storage_key == (
        "exports/60000000-0000-0000-0000-000000000006.docx"
    )
    assert artifact.size_bytes == 8192


def test_save_review_revision_rejects_source_version_mismatch(
    db_session: Session,
) -> None:
    _create_job(db_session)
    repository = VerificationRepository(db_session)
    repository.save_result(JOB_ID, _result())

    with pytest.raises(ValueError, match="source version"):
        repository.save_review_revision(
            review_revision_id=REVISION_ID,
            verification_run_id=RUN_ID,
            source_version="sha256:different-source",
            revision_number=1,
            text="账号测试\n第二行",
            created_at=CREATED_AT + timedelta(minutes=1),
        )


def test_database_rejects_run_document_from_another_job(db_session: Session) -> None:
    _seed_two_results(db_session)

    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                "UPDATE verification_runs "
                "SET document_id = :document_id "
                "WHERE verification_run_id = :verification_run_id"
            ),
            {
                "document_id": SECOND_DOCUMENT_ID,
                "verification_run_id": RUN_ID,
            },
        )
    db_session.rollback()


def test_database_rejects_issue_document_from_another_run(db_session: Session) -> None:
    _seed_two_results(db_session)

    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                "UPDATE verification_issues "
                "SET document_id = :document_id "
                "WHERE verification_run_id = :verification_run_id"
            ),
            {
                "document_id": SECOND_DOCUMENT_ID,
                "verification_run_id": RUN_ID,
            },
        )
    db_session.rollback()


def test_database_rejects_review_document_and_source_from_another_run(
    db_session: Session,
) -> None:
    _seed_two_results(db_session)
    repository = VerificationRepository(db_session)
    repository.save_review_revision(
        review_revision_id=REVISION_ID,
        verification_run_id=RUN_ID,
        source_version="sha256:source-v7",
        revision_number=1,
        text="账号测试",
        created_at=CREATED_AT,
    )
    repository.commit()

    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                "UPDATE review_revisions "
                "SET document_id = :document_id "
                "WHERE review_revision_id = :review_revision_id"
            ),
            {
                "document_id": SECOND_DOCUMENT_ID,
                "review_revision_id": REVISION_ID,
            },
        )
    db_session.rollback()

    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                "UPDATE review_revisions "
                "SET source_version = :source_version "
                "WHERE review_revision_id = :review_revision_id"
            ),
            {
                "source_version": "sha256:different-source",
                "review_revision_id": REVISION_ID,
            },
        )
    db_session.rollback()


def test_database_rejects_artifact_revision_from_another_run(
    db_session: Session,
) -> None:
    _seed_two_results(db_session)
    repository = VerificationRepository(db_session)
    repository.save_review_revision(
        review_revision_id=SECOND_REVISION_ID,
        verification_run_id=SECOND_RUN_ID,
        source_version="sha256:source-v7",
        revision_number=1,
        text="账号测试",
        created_at=CREATED_AT,
    )
    repository.save_export_artifact(
        export_artifact_id=ARTIFACT_ID,
        verification_run_id=RUN_ID,
        review_revision_id=None,
        source_version="sha256:source-v7",
        file_type=FileType.DOCX,
        file_name="sample.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        storage_key="exports/cross-owner.docx",
        size_bytes=10,
        created_at=CREATED_AT,
    )
    repository.commit()

    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                "UPDATE export_artifacts "
                "SET review_revision_id = :review_revision_id "
                "WHERE export_artifact_id = :export_artifact_id"
            ),
            {
                "review_revision_id": SECOND_REVISION_ID,
                "export_artifact_id": ARTIFACT_ID,
            },
        )
    db_session.rollback()


def test_concurrent_identical_result_retries_serialize_and_succeed(
    db_session_factory: sessionmaker[Session],
) -> None:
    seed_session = db_session_factory()
    try:
        _create_job(seed_session)
    finally:
        seed_session.close()

    result = _result()
    first_saved = Event()
    second_started = Event()
    second_finished = Event()
    allow_first_commit = Event()

    def first_worker() -> None:
        session = db_session_factory()
        repository = VerificationRepository(session)
        try:
            session.execute(text("SET lock_timeout = '4s'"))
            repository.save_result(JOB_ID, result)
            first_saved.set()
            if not allow_first_commit.wait(timeout=2):
                raise TimeoutError("timed out waiting to commit the first result")
            repository.commit()
        except Exception:
            repository.rollback()
            raise
        finally:
            session.close()

    def second_worker() -> None:
        session = db_session_factory()
        repository = VerificationRepository(session)
        try:
            session.execute(text("SET lock_timeout = '4s'"))
            second_started.set()
            repository.save_result(JOB_ID, result)
            repository.commit()
        except Exception:
            repository.rollback()
            raise
        finally:
            second_finished.set()
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(first_worker)
        assert first_saved.wait(timeout=2)
        second_future = executor.submit(second_worker)
        assert second_started.wait(timeout=1)
        assert not second_finished.wait(timeout=0.2)
        allow_first_commit.set()
        first_future.result(timeout=5)
        second_future.result(timeout=5)

    verification_session = db_session_factory()
    try:
        assert VerificationRepository(verification_session).get_result_for_job(
            JOB_ID
        ) == result
    finally:
        verification_session.close()


def test_concurrent_review_revision_conflict_raises_value_error(
    db_session_factory: sessionmaker[Session],
) -> None:
    seed_session = db_session_factory()
    try:
        _create_job(seed_session)
        repository = VerificationRepository(seed_session)
        repository.save_result(JOB_ID, _result())
        repository.commit()
    finally:
        seed_session.close()

    first_saved = Event()
    second_started = Event()
    second_finished = Event()
    allow_first_commit = Event()

    def first_worker() -> None:
        session = db_session_factory()
        repository = VerificationRepository(session)
        try:
            session.execute(text("SET lock_timeout = '4s'"))
            repository.save_review_revision(
                review_revision_id=REVISION_ID,
                verification_run_id=RUN_ID,
                source_version="sha256:source-v7",
                revision_number=1,
                text="first",
                created_at=CREATED_AT,
            )
            first_saved.set()
            if not allow_first_commit.wait(timeout=2):
                raise TimeoutError("timed out waiting to commit the first revision")
            repository.commit()
        except Exception:
            repository.rollback()
            raise
        finally:
            session.close()

    def second_worker() -> Exception | None:
        session = db_session_factory()
        repository = VerificationRepository(session)
        try:
            session.execute(text("SET lock_timeout = '4s'"))
            second_started.set()
            repository.save_review_revision(
                review_revision_id=SECOND_REVISION_ID,
                verification_run_id=RUN_ID,
                source_version="sha256:source-v7",
                revision_number=1,
                text="second",
                created_at=CREATED_AT,
            )
            repository.commit()
            return None
        except Exception as error:
            repository.rollback()
            return error
        finally:
            second_finished.set()
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(first_worker)
        assert first_saved.wait(timeout=2)
        second_future = executor.submit(second_worker)
        assert second_started.wait(timeout=1)
        assert not second_finished.wait(timeout=0.2)
        allow_first_commit.set()
        first_future.result(timeout=5)
        error = second_future.result(timeout=5)

    assert isinstance(error, ValueError)
    assert not isinstance(error, IntegrityError)


def test_concurrent_cross_run_artifact_conflict_raises_value_error(
    db_session_factory: sessionmaker[Session],
) -> None:
    seed_session = db_session_factory()
    try:
        _seed_two_results(seed_session)
    finally:
        seed_session.close()

    storage_key = "exports/concurrent.docx"
    first_saved = Event()
    second_started = Event()
    second_finished = Event()
    allow_first_commit = Event()

    def first_worker() -> None:
        session = db_session_factory()
        repository = VerificationRepository(session)
        try:
            session.execute(text("SET lock_timeout = '4s'"))
            repository.save_export_artifact(
                export_artifact_id=ARTIFACT_ID,
                verification_run_id=RUN_ID,
                review_revision_id=None,
                source_version="sha256:source-v7",
                file_type=FileType.DOCX,
                file_name="first.docx",
                media_type="application/octet-stream",
                storage_key=storage_key,
                size_bytes=10,
                created_at=CREATED_AT,
            )
            first_saved.set()
            if not allow_first_commit.wait(timeout=2):
                raise TimeoutError("timed out waiting to commit the first artifact")
            repository.commit()
        except Exception:
            repository.rollback()
            raise
        finally:
            session.close()

    def second_worker() -> Exception | None:
        session = db_session_factory()
        repository = VerificationRepository(session)
        try:
            session.execute(text("SET lock_timeout = '4s'"))
            second_started.set()
            repository.save_export_artifact(
                export_artifact_id=SECOND_ARTIFACT_ID,
                verification_run_id=SECOND_RUN_ID,
                review_revision_id=None,
                source_version="sha256:source-v7",
                file_type=FileType.DOCX,
                file_name="second.docx",
                media_type="application/octet-stream",
                storage_key=storage_key,
                size_bytes=10,
                created_at=CREATED_AT,
            )
            repository.commit()
            return None
        except Exception as error:
            repository.rollback()
            return error
        finally:
            second_finished.set()
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(first_worker)
        assert first_saved.wait(timeout=2)
        second_future = executor.submit(second_worker)
        assert second_started.wait(timeout=1)
        assert not second_finished.wait(timeout=0.2)
        allow_first_commit.set()
        first_future.result(timeout=5)
        error = second_future.result(timeout=5)

    assert isinstance(error, ValueError)
    assert not isinstance(error, IntegrityError)


def test_get_result_for_job_returns_none_when_job_has_no_run(db_session: Session) -> None:
    _create_job(db_session)

    assert VerificationRepository(db_session).get_result_for_job(JOB_ID) is None


def _create_job(
    db_session: Session,
    *,
    job_id: UUID = JOB_ID,
    source_name: str = "sample.docx",
    file_type: FileType = FileType.DOCX,
) -> None:
    repository = JobRepository(db_session)
    repository.create_job(
        job_id=job_id,
        source_name=source_name,
        file_type=file_type.value,
        size_bytes=4096,
        storage_key=str(job_id),
        created_at=CREATED_AT,
        expires_at=CREATED_AT + timedelta(days=1),
    )
    repository.commit()


def _result(
    *,
    document_id: UUID = DOCUMENT_ID,
    verification_run_id: UUID = RUN_ID,
    issue_id: UUID = ISSUE_ID,
    source_name: str = "sample.docx",
    file_type: FileType = FileType.DOCX,
) -> VerificationResult:
    issue = Issue(
        issue_id=issue_id,
        document_id=document_id,
        verification_run_id=verification_run_id,
        block_id="paragraph-7",
        page=3,
        start=0,
        end=2,
        block_start=4,
        block_end=6,
        original="帐号",
        suggestion="账号",
        alternatives=["账户", "账号名称"],
        type="typo",
        severity=IssueSeverity.WARNING,
        layer="character",
        message="建议使用规范词形",
        description="“帐号”应改为“账号”",
        rule_id="cn_typo_account",
        rule_version="2026.08",
        source="compatibility.analyzer",
        source_version="ruleset:2026.08.31",
        confidence=0.97,
        auto_fixable=True,
        context="帐号测试",
        review="uncertain",
        review_reason="需要结合业务术语确认",
    )
    return VerificationResult(
        verification_run_id=verification_run_id,
        document_id=document_id,
        source_version="sha256:source-v7",
        source_name=source_name,
        file_type=file_type,
        scenario=Scenario.BUSINESS,
        text="帐号测试\n第二行",
        blocks=(
            TextBlock(
                block_id="paragraph-7",
                kind="paragraph",
                text="帐号测试\n第二行",
                global_start=0,
                global_end=8,
                block_start=0,
                block_end=8,
                page=3,
                paragraph_index=7,
                table_index=None,
                row_index=None,
                cell_index=None,
                bbox=None,
                parent_id=None,
                style={},
                source_locator={"page": 3, "paragraph_index": 7},
            ),
        ),
        parser_name="compatibility-docx",
        parser_version="1",
        stats=VerificationStatistics(
            char_count=8,
            char_count_no_space=8,
            line_count=2,
            paragraph_count=2,
            language="zh",
            primary_count=7,
            primary_label="中文字符",
        ),
        issues=(issue,),
        summary=VerificationSummary(
            total=1,
            by_type={"typo": 1},
            by_severity={"warning": 1},
            by_rule={"cn_typo_account": 1},
            by_layer={"character": 1},
            llm_review={
                "performed": True,
                "reviewed": 1,
                "provider": {"name": "openai", "model": "gpt-test"},
            },
        ),
        execution_mode=VerificationExecutionMode.ASYNCHRONOUS,
        analysis_mode=VerificationAnalysisMode.LOCAL_PLUS_LLM,
        dictionary_versions={
            "chinese_terms": "sha256:terms-v4",
            "sensitive_words": "sha256:sensitive-v2",
        },
        degradation=VerificationDegradation(
            is_degraded=True,
            reasons=("llm_review_failed", "provider_timeout"),
        ),
    )


def _structured_result() -> VerificationResult:
    text_value = "帐号测试\n第二行"
    blocks = (
        TextBlock(
            block_id="heading-0",
            kind="heading",
            text="帐号测试",
            global_start=0,
            global_end=4,
            block_start=0,
            block_end=4,
            page=1,
            paragraph_index=0,
            table_index=None,
            row_index=None,
            cell_index=None,
            bbox=(1.0, 2.0, 3.0, 4.0),
            parent_id="body-0",
            style={"level": 1},
            source_locator={"page": 1, "paragraph_index": 0, "source": "heading"},
        ),
        TextBlock(
            block_id="body-0",
            kind="paragraph",
            text=text_value,
            global_start=0,
            global_end=len(text_value),
            block_start=0,
            block_end=len(text_value),
            page=None,
            paragraph_index=None,
            table_index=None,
            row_index=None,
            cell_index=None,
            bbox=None,
            parent_id=None,
            style={"section": "body"},
            source_locator={"source": "document"},
        ),
        TextBlock(
            block_id="table-cell-0",
            kind="table_cell",
            text="第二行",
            global_start=5,
            global_end=8,
            block_start=0,
            block_end=3,
            page=2,
            paragraph_index=4,
            table_index=1,
            row_index=2,
            cell_index=3,
            bbox=(10.5, 20.5, 30.5, 40.5),
            parent_id="body-0",
            style={"font": {"family": "Noto Sans", "bold": True}},
            source_locator={
                "page": 2,
                "paragraph_index": 4,
                "table_index": 1,
                "row_index": 2,
                "cell_index": 3,
                "source": "table",
            },
        ),
    )
    return VerificationResult(
        verification_run_id=RUN_ID,
        document_id=DOCUMENT_ID,
        source_version="sha256:source-v7",
        source_name="sample.docx",
        file_type=FileType.DOCX,
        scenario=Scenario.BUSINESS,
        text=text_value,
        blocks=blocks,
        parser_name="structured-parser",
        parser_version="7.2",
        stats=VerificationStatistics(
            char_count=8,
            char_count_no_space=8,
            line_count=2,
            paragraph_count=2,
            language="zh",
            primary_count=7,
            primary_label="中文字符",
        ),
        issues=(),
        summary=VerificationSummary(total=0),
        execution_mode=VerificationExecutionMode.ASYNCHRONOUS,
        analysis_mode=VerificationAnalysisMode.LOCAL_ONLY,
        dictionary_versions={},
        degradation=VerificationDegradation(),
    )


def _seed_two_results(db_session: Session) -> None:
    _create_job(db_session)
    _create_job(db_session, job_id=SECOND_JOB_ID)
    repository = VerificationRepository(db_session)
    repository.save_result(JOB_ID, _result())
    repository.save_result(
        SECOND_JOB_ID,
        _result(
            document_id=SECOND_DOCUMENT_ID,
            verification_run_id=SECOND_RUN_ID,
            issue_id=SECOND_ISSUE_ID,
        ),
    )
    repository.commit()


def _metadata_foreign_keys(
    row_type: type[object],
) -> set[tuple[tuple[str, ...], tuple[str, ...], str | None]]:
    return {
        (
            tuple(element.parent.name for element in constraint.elements),
            tuple(element.target_fullname for element in constraint.elements),
            constraint.ondelete,
        )
        for constraint in row_type.__table__.foreign_key_constraints  # type: ignore[attr-defined]
    }


def _unique_names(inspector: Inspector, table_name: str) -> set[str | None]:
    return {
        constraint["name"]
        for constraint in inspector.get_unique_constraints(table_name)
    }


def _foreign_keys(
    inspector: Inspector,
    table_name: str,
) -> set[tuple[str, tuple[str, ...], tuple[str, ...], str | None]]:
    return {
        (
            foreign_key["referred_table"],
            tuple(foreign_key["constrained_columns"]),
            tuple(foreign_key["referred_columns"]),
            foreign_key["options"].get("ondelete"),
        )
        for foreign_key in inspector.get_foreign_keys(table_name)
    }
