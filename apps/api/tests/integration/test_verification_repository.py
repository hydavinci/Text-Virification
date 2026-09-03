import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from threading import Event
from time import monotonic
from uuid import UUID, uuid4

import pytest
from sqlalchemy import CheckConstraint, Engine, String, Text, func, inspect, select, text
from sqlalchemy.engine.reflection import Inspector
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.session import sessionmaker

from alembic import command
from text_verification.application import (
    ArtifactLifecycleStatus,
    ArtifactPendingReconciliationService,
    ArtifactPersistenceRequest,
    ArtifactPersistenceResult,
    ArtifactPersistenceService,
    ArtifactReservation,
)
from text_verification.document_processing.pdf_models import (
    OcrRequirement,
    PdfCharacterMappingState,
    PdfDocumentMetadata,
    PdfPageKind,
    PdfPageMetadata,
    PdfTable,
    PdfTableCell,
    PdfTextCharacter,
    PdfTextSpan,
)
from text_verification.domain.artifacts import ArtifactFinalizationRejection
from text_verification.domain.documents import DocumentMetadata, FileType, TextBlock
from text_verification.domain.issues import Issue, IssueSeverity
from text_verification.domain.jobs import JobStatus
from text_verification.domain.verification import (
    DocumentRevisionKind,
    PersistedDocumentRevision,
    ReviewRevisionDraft,
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
    JobRow,
    ReviewRevisionRow,
    VerificationIssueRow,
    VerificationRunRow,
)
from text_verification.infrastructure.repositories import JobRepository
from text_verification.infrastructure.storage import (
    InvalidUpload,
    JobStorage,
    build_artifact_storage_key,
)
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
ARTIFACT_STORAGE_KEY = build_artifact_storage_key(
    JOB_ID,
    ARTIFACT_ID,
    FileType.DOCX,
)


@pytest.fixture
def artifact_storage(tmp_path: Path) -> JobStorage:
    return JobStorage(tmp_path / "storage", max_upload_bytes=1024 * 1024)


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


def test_result_row_mapping_round_trips_typed_document_metadata() -> None:
    requirement = OcrRequirement(mode="partial", pages=(1,))
    result = _result().model_copy(
        update={
            "metadata": DocumentMetadata(
                pdf=PdfDocumentMetadata(
                    pages=(
                        PdfPageMetadata(
                            page=1,
                            kind=PdfPageKind.MIXED,
                            page_bbox=(0.0, 0.0, 100.0, 200.0),
                            text_length=10,
                            text_density=0.0005,
                            image_coverage=0.8,
                            ocr_required=True,
                            spans=(
                                PdfTextSpan(
                                    text="A",
                                    bbox=(1.0, 2.0, 9.0, 12.0),
                                    font_name="Helvetica",
                                    font_size=10.0,
                                    font_flags=0,
                                    color=0,
                                    span_index=0,
                                    characters=(
                                        PdfTextCharacter(
                                            text="A",
                                            bbox=(1.0, 2.0, 9.0, 12.0),
                                            source_start=0,
                                            source_end=1,
                                            mapping_state=PdfCharacterMappingState.GLYPH,
                                            group_id="line-0-span-0-glyph-0",
                                            line_direction=(-1.0, 0.0),
                                            writing_mode=0,
                                            raw_line_index=2,
                                            span_order=3,
                                        ),
                                    ),
                                    line_direction=(-1.0, 0.0),
                                    writing_mode=0,
                                    line_index=2,
                                    span_order=3,
                                ),
                            ),
                            tables=(
                                PdfTable(
                                    table_index=0,
                                    bbox=(20.0, 20.0, 40.0, 40.0),
                                    row_count=1,
                                    column_count=1,
                                    rows=(
                                        (
                                            PdfTableCell(
                                                text="A",
                                                bbox=(20.0, 20.0, 40.0, 40.0),
                                                table_index=0,
                                                row_index=0,
                                                cell_index=0,
                                                characters=(
                                                    PdfTextCharacter(
                                                        text="A",
                                                        bbox=(20.0, 20.0, 30.0, 30.0),
                                                        source_start=0,
                                                        source_end=1,
                                                        mapping_state=PdfCharacterMappingState.GLYPH,
                                                        group_id="line-2-span-3-glyph-0",
                                                        line_direction=(-1.0, 0.0),
                                                        writing_mode=0,
                                                        raw_line_index=2,
                                                        span_order=3,
                                                    ),
                                                ),
                                            ),
                                        ),
                                    ),
                                ),
                            ),
                        ),
                    ),
                    ocr_requirement=requirement,
                )
            ),
            "ocr_requirement": requirement,
        }
    )

    document_row, run_row = _map_result_to_rows(JOB_ID, result, created_at=CREATED_AT)
    loaded = _map_rows_to_result(document_row, run_row)

    assert document_row.document_metadata == result.metadata.model_dump(mode="json")
    assert loaded == result
    aligned_character = loaded.metadata.pdf.pages[0].tables[0].rows[0][0].characters[0]
    assert (
        aligned_character.line_direction,
        aligned_character.writing_mode.value,
        aligned_character.raw_line_index,
        aligned_character.span_order,
        aligned_character.group_id,
    ) == ((-1.0, 0.0), 0, 2, 3, "line-2-span-3-glyph-0")
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


def test_export_artifact_orm_defines_optional_sha256_digest() -> None:
    column = ExportArtifactRow.__table__.c.content_sha256

    assert isinstance(column.type, String)
    assert column.type.length == 64
    assert column.nullable is True
    assert {
        constraint.name
        for constraint in ExportArtifactRow.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    } >= {"ck_export_artifacts_sha256"}


def test_export_artifact_orm_defines_pending_ready_lifecycle() -> None:
    columns = ExportArtifactRow.__table__.c

    assert columns.status.nullable is False
    assert columns.reserved_at.nullable is False
    assert columns.ready_at.nullable is True
    assert {
        constraint.name
        for constraint in ExportArtifactRow.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    } >= {
        "ck_export_artifacts_status",
        "ck_export_artifacts_ready_state",
        "ck_export_artifacts_pending_digest",
    }
    assert {index.name for index in ExportArtifactRow.__table__.indexes} >= {
        "ix_export_artifacts_status_reserved_at"
    }


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
        ("document_id", "block_id"),
        ("document_blocks.document_id", "document_blocks.block_id"),
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
    artifact_columns = {
        column["name"]: column for column in inspector.get_columns("export_artifacts")
    }
    assert artifact_columns["content_sha256"]["nullable"] is True
    assert artifact_columns["status"]["nullable"] is False
    assert artifact_columns["reserved_at"]["nullable"] is False
    assert artifact_columns["ready_at"]["nullable"] is True
    assert {
        constraint["name"]
        for constraint in inspector.get_check_constraints("export_artifacts")
    } >= {
        "ck_export_artifacts_sha256",
        "ck_export_artifacts_status",
        "ck_export_artifacts_ready_state",
        "ck_export_artifacts_pending_digest",
    }
    assert {
        index["name"] for index in inspector.get_indexes("export_artifacts")
    } >= {"ix_export_artifacts_status_reserved_at"}
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
        "document_blocks",
        ("document_id", "block_id"),
        ("document_id", "block_id"),
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


def test_upgrade_from_0004_marks_legacy_artifacts_ready(
    db_engine: Engine,
    alembic_config,
) -> None:
    job_id = UUID("10000000-0000-0000-0000-000000000091")
    document_id = UUID("20000000-0000-0000-0000-000000000092")
    run_id = UUID("30000000-0000-0000-0000-000000000093")
    artifact_id = UUID("60000000-0000-0000-0000-000000000094")
    created_at = datetime(2026, 9, 1, 3, 0, tzinfo=UTC)
    storage_key = build_artifact_storage_key(job_id, artifact_id, FileType.TXT)

    try:
        command.downgrade(alembic_config, "0004_finalize_verification_pipeline")
        session = Session(db_engine)
        try:
            _create_job(
                session,
                job_id=job_id,
                source_name="legacy.txt",
                file_type=FileType.TXT,
            )
            VerificationRepository(session).save_result(
                job_id,
                _result(
                    document_id=document_id,
                    verification_run_id=run_id,
                    issue_id=uuid4(),
                    source_name="legacy.txt",
                    file_type=FileType.TXT,
                ),
            )
            session.commit()
        finally:
            session.close()
        with db_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO export_artifacts ("
                    "export_artifact_id, verification_run_id, review_revision_id, "
                    "source_version, file_type, file_name, media_type, storage_key, "
                    "size_bytes, created_at"
                    ") VALUES ("
                    ":artifact_id, :run_id, NULL, :source_version, 'txt', "
                    "'legacy.txt', 'text/plain', :storage_key, 6, :created_at"
                    ")"
                ),
                {
                    "artifact_id": artifact_id,
                    "run_id": run_id,
                    "source_version": "sha256:source-v7",
                    "storage_key": storage_key,
                    "created_at": created_at,
                },
            )

        command.upgrade(alembic_config, "head")

        with db_engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT content_sha256, status, reserved_at, ready_at "
                    "FROM export_artifacts "
                    "WHERE export_artifact_id = :artifact_id"
                ),
                {"artifact_id": artifact_id},
            ).one()
        assert row == (None, "ready", created_at, created_at)
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
    assert loaded.issues[0].block_start == 0
    assert loaded.issues[0].block_end == 2
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
    artifact_storage: JobStorage,
) -> None:
    request = _artifact_request(
        review_revision_id=REVISION_ID,
        file_name="sample-reviewed.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        data=b"x" * 8192,
        created_at=CREATED_AT + timedelta(minutes=2),
    )
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
    repository.commit()
    service = _artifact_service_for_session(artifact_storage, db_session)
    first = service.persist(request)
    repository.save_review_revision(
        review_revision_id=REVISION_ID,
        verification_run_id=RUN_ID,
        source_version="sha256:source-v7",
        revision_number=1,
        text="账号测试\n第二行",
        created_at=CREATED_AT + timedelta(minutes=1),
    )
    repository.commit()
    second = service.persist(request)
    db_session.expire_all()

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
    assert artifact.storage_key == ARTIFACT_STORAGE_KEY
    assert artifact.size_bytes == 8192
    assert artifact.content_sha256 == first.content_sha256
    assert first.created is True
    assert second.created is False


def test_persist_review_revision_allocates_server_numbers_and_preserves_parent_chain(
    db_session: Session,
) -> None:
    _create_job(db_session)
    repository = VerificationRepository(db_session)
    repository.save_result(JOB_ID, _result())
    first_draft = ReviewRevisionDraft(
        revision_id=REVISION_ID,
        document_id=DOCUMENT_ID,
        verification_run_id=RUN_ID,
        source_version="sha256:source-v7",
        parent_revision_id=None,
        kind=DocumentRevisionKind.REVIEW,
        text="账号测试\n第二行",
    )
    second_draft = ReviewRevisionDraft(
        revision_id=SECOND_REVISION_ID,
        document_id=DOCUMENT_ID,
        verification_run_id=RUN_ID,
        source_version="sha256:source-v7",
        parent_revision_id=REVISION_ID,
        kind=DocumentRevisionKind.MANUAL,
        text="最终文本",
    )

    first = repository.persist_review_revision(
        JOB_ID,
        first_draft,
        created_at=CREATED_AT + timedelta(minutes=1),
    )
    second = repository.persist_review_revision(
        JOB_ID,
        second_draft,
        created_at=CREATED_AT + timedelta(minutes=2),
    )
    retried = repository.persist_review_revision(
        JOB_ID,
        first_draft,
        created_at=CREATED_AT + timedelta(minutes=3),
    )
    repository.commit()

    assert first == PersistedDocumentRevision(
        **first_draft.model_dump(),
        revision_number=1,
        created_at=CREATED_AT + timedelta(minutes=1),
    )
    assert second == PersistedDocumentRevision(
        **second_draft.model_dump(),
        revision_number=2,
        created_at=CREATED_AT + timedelta(minutes=2),
    )
    assert retried == first
    rows = db_session.scalars(
        select(ReviewRevisionRow).order_by(ReviewRevisionRow.revision_number)
    ).all()
    assert [row.parent_revision_id for row in rows] == [None, REVISION_ID]
    assert [row.kind for row in rows] == ["review", "manual"]


@pytest.mark.parametrize(
    ("job_id", "draft_update", "message"),
    [
        (
            SECOND_JOB_ID,
            {},
            "requested job",
        ),
        (
            JOB_ID,
            {"document_id": SECOND_DOCUMENT_ID},
            "document",
        ),
        (
            JOB_ID,
            {"source_version": "sha256:stale"},
            "source version",
        ),
        (
            JOB_ID,
            {"parent_revision_id": SECOND_REVISION_ID},
            "parent revision",
        ),
    ],
)
def test_persist_review_revision_rejects_foreign_or_stale_identity(
    db_session: Session,
    job_id: UUID,
    draft_update: dict[str, object],
    message: str,
) -> None:
    _create_job(db_session)
    repository = VerificationRepository(db_session)
    repository.save_result(JOB_ID, _result())
    draft = ReviewRevisionDraft(
        revision_id=REVISION_ID,
        document_id=DOCUMENT_ID,
        verification_run_id=RUN_ID,
        source_version="sha256:source-v7",
        parent_revision_id=None,
        kind=DocumentRevisionKind.REVIEW,
        text="账号测试",
    ).model_copy(update=draft_update)

    with pytest.raises((LookupError, ValueError), match=message):
        repository.persist_review_revision(
            job_id,
            draft,
            created_at=CREATED_AT,
        )


def test_persist_review_revision_rejects_stale_parent_after_newer_revision(
    db_session: Session,
) -> None:
    _create_job(db_session)
    repository = VerificationRepository(db_session)
    repository.save_result(JOB_ID, _result())
    first = ReviewRevisionDraft(
        revision_id=REVISION_ID,
        document_id=DOCUMENT_ID,
        verification_run_id=RUN_ID,
        source_version="sha256:source-v7",
        parent_revision_id=None,
        kind=DocumentRevisionKind.REVIEW,
        text="账号测试",
    )
    repository.persist_review_revision(JOB_ID, first, created_at=CREATED_AT)

    with pytest.raises(ValueError, match="latest persisted revision"):
        repository.persist_review_revision(
            JOB_ID,
            ReviewRevisionDraft(
                revision_id=SECOND_REVISION_ID,
                document_id=DOCUMENT_ID,
                verification_run_id=RUN_ID,
                source_version="sha256:source-v7",
                parent_revision_id=None,
                kind=DocumentRevisionKind.MANUAL,
                text="分叉文本",
            ),
            created_at=CREATED_AT + timedelta(minutes=1),
        )


def test_reserve_export_artifact_rejects_a_superseded_review_revision(
    db_session: Session,
) -> None:
    _create_job(db_session)
    repository = VerificationRepository(db_session)
    repository.save_result(JOB_ID, _result())
    first = repository.persist_review_revision(
        JOB_ID,
        ReviewRevisionDraft(
            revision_id=REVISION_ID,
            document_id=DOCUMENT_ID,
            verification_run_id=RUN_ID,
            source_version="sha256:source-v7",
            parent_revision_id=None,
            kind=DocumentRevisionKind.REVIEW,
            text="first",
        ),
        created_at=CREATED_AT,
    )
    repository.persist_review_revision(
        JOB_ID,
        ReviewRevisionDraft(
            revision_id=SECOND_REVISION_ID,
            document_id=DOCUMENT_ID,
            verification_run_id=RUN_ID,
            source_version="sha256:source-v7",
            parent_revision_id=first.revision_id,
            kind=DocumentRevisionKind.MANUAL,
            text="second",
        ),
        created_at=CREATED_AT + timedelta(minutes=1),
    )

    with pytest.raises(ValueError, match="latest persisted revision"):
        repository.reserve_export_artifact(
            export_artifact_id=ARTIFACT_ID,
            verification_run_id=RUN_ID,
            review_revision_id=first.revision_id,
            source_version="sha256:source-v7",
            file_type=FileType.DOCX,
            file_name="sample.docx",
            media_type="application/octet-stream",
            storage_key=ARTIFACT_STORAGE_KEY,
            size_bytes=1,
            content_sha256="0" * 64,
            reserved_at=CREATED_AT,
            created_at=CREATED_AT,
        )


def test_finalize_export_artifact_deletes_reservation_if_revision_became_stale(
    db_session: Session,
) -> None:
    _create_job(db_session)
    repository = VerificationRepository(db_session)
    repository.save_result(JOB_ID, _result())
    first = repository.persist_review_revision(
        JOB_ID,
        ReviewRevisionDraft(
            revision_id=REVISION_ID,
            document_id=DOCUMENT_ID,
            verification_run_id=RUN_ID,
            source_version="sha256:source-v7",
            parent_revision_id=None,
            kind=DocumentRevisionKind.REVIEW,
            text="first",
        ),
        created_at=CREATED_AT,
    )
    reservation = repository.reserve_export_artifact(
        export_artifact_id=ARTIFACT_ID,
        verification_run_id=RUN_ID,
        review_revision_id=first.revision_id,
        source_version="sha256:source-v7",
        file_type=FileType.DOCX,
        file_name="sample.docx",
        media_type="application/octet-stream",
        storage_key=ARTIFACT_STORAGE_KEY,
        size_bytes=1,
        content_sha256="0" * 64,
        reserved_at=CREATED_AT,
        created_at=CREATED_AT,
    )
    repository.persist_review_revision(
        JOB_ID,
        ReviewRevisionDraft(
            revision_id=SECOND_REVISION_ID,
            document_id=DOCUMENT_ID,
            verification_run_id=RUN_ID,
            source_version="sha256:source-v7",
            parent_revision_id=first.revision_id,
            kind=DocumentRevisionKind.MANUAL,
            text="second",
        ),
        created_at=CREATED_AT + timedelta(minutes=1),
    )

    result = repository.finalize_export_artifact(
        reservation,
        ready_at=CREATED_AT + timedelta(minutes=2),
        consistency_check=lambda: None,
        require_current_result=True,
    )

    assert result is ArtifactFinalizationRejection.STALE_REVISION
    assert repository.read_export_artifact(ARTIFACT_ID) is None


def test_reserve_export_artifact_rejects_key_for_another_job(
    db_session: Session,
) -> None:
    storage_key = build_artifact_storage_key(
        SECOND_JOB_ID,
        ARTIFACT_ID,
        FileType.DOCX,
    )
    _create_job(db_session)
    repository = VerificationRepository(db_session)
    repository.save_result(JOB_ID, _result())
    repository.commit()

    with pytest.raises(ValueError, match="does not belong"):
        repository.reserve_export_artifact(
            export_artifact_id=ARTIFACT_ID,
            verification_run_id=RUN_ID,
            review_revision_id=None,
            source_version="sha256:source-v7",
            file_type=FileType.DOCX,
            file_name="sample.docx",
            media_type="application/octet-stream",
            storage_key=storage_key,
            size_bytes=10,
            content_sha256="0" * 64,
            reserved_at=CREATED_AT,
            created_at=CREATED_AT,
        )


def test_symlink_backed_artifact_is_rejected_before_metadata_persistence(
    db_session: Session,
    artifact_storage: JobStorage,
    tmp_path: Path,
) -> None:
    _create_job(db_session)
    repository = VerificationRepository(db_session)
    repository.save_result(JOB_ID, _result())
    repository.commit()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = artifact_storage._root / "artifacts" / str(JOB_ID) / "link"
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlink creation unavailable: {error}")
    storage_key = build_artifact_storage_key(
        JOB_ID,
        ARTIFACT_ID,
        FileType.DOCX,
        subdirectories=("link",),
    )

    request = ArtifactPersistenceRequest(
        job_id=JOB_ID,
        export_artifact_id=ARTIFACT_ID,
        verification_run_id=RUN_ID,
        review_revision_id=None,
        source_version="sha256:source-v7",
        file_type=FileType.DOCX,
        file_name="sample.docx",
        media_type="application/octet-stream",
        storage_key=storage_key,
        data=b"must not escape",
        created_at=CREATED_AT,
    )
    with pytest.raises(InvalidUpload, match="unsafe directory entry"):
        _artifact_service_for_session(
            artifact_storage,
            db_session,
        ).persist(
            request
        )

    db_session.expire_all()
    pending = db_session.get(ExportArtifactRow, ARTIFACT_ID)
    assert pending is not None
    assert pending.status == "pending"
    assert list(outside.iterdir()) == []


def test_artifact_service_compensates_wrong_job_rejection(
    db_session: Session,
    artifact_storage: JobStorage,
) -> None:
    _create_job(db_session)
    repository = VerificationRepository(db_session)
    repository.save_result(JOB_ID, _result())
    repository.commit()
    request = _artifact_request(
        job_id=SECOND_JOB_ID,
        data=b"wrong job",
    )

    with pytest.raises(ValueError, match="does not belong"):
        _artifact_service_for_session(artifact_storage, db_session).persist(request)

    assert not (artifact_storage._root / request.storage_key).exists()
    assert db_session.scalar(select(func.count()).select_from(ExportArtifactRow)) == 0


def test_artifact_service_compensates_source_version_rejection(
    db_session: Session,
    artifact_storage: JobStorage,
) -> None:
    _create_job(db_session)
    repository = VerificationRepository(db_session)
    repository.save_result(JOB_ID, _result())
    repository.commit()
    request = _artifact_request(
        source_version="sha256:different",
        data=b"wrong source",
    )

    with pytest.raises(ValueError, match="source version"):
        _artifact_service_for_session(artifact_storage, db_session).persist(request)

    assert not (artifact_storage._root / request.storage_key).exists()
    assert db_session.scalar(select(func.count()).select_from(ExportArtifactRow)) == 0


def test_artifact_service_keeps_idempotent_file_after_metadata_conflict(
    db_session: Session,
    artifact_storage: JobStorage,
) -> None:
    _create_job(db_session)
    repository = VerificationRepository(db_session)
    repository.save_result(JOB_ID, _result())
    repository.commit()
    first_request = _artifact_request(
        file_name="first.docx",
        data=b"idempotent",
    )
    service = _artifact_service_for_session(artifact_storage, db_session)
    first = service.persist(first_request)
    conflicting_request = _artifact_request(
        file_name="different.docx",
        data=b"idempotent",
    )

    with pytest.raises(ValueError, match="different data"):
        service.persist(conflicting_request)

    db_session.expire_all()
    artifact = db_session.get(ExportArtifactRow, ARTIFACT_ID)
    assert first.path.read_bytes() == b"idempotent"
    assert artifact is not None
    assert artifact.file_name == "first.docx"
    assert artifact.content_sha256 == first.content_sha256


def test_legacy_ready_artifact_with_null_digest_is_lazily_fingerprinted(
    db_session_factory: sessionmaker[Session],
    artifact_storage: JobStorage,
) -> None:
    seed_session = db_session_factory()
    request = _artifact_request(data=b"legacy")
    try:
        _create_job(seed_session)
        repository = VerificationRepository(seed_session)
        repository.save_result(JOB_ID, _result())
        repository.commit()
        seed_session.add(
            ExportArtifactRow(
                export_artifact_id=ARTIFACT_ID,
                verification_run_id=RUN_ID,
                review_revision_id=None,
                source_version=request.source_version,
                file_type=request.file_type.value,
                file_name=request.file_name,
                media_type=request.media_type,
                storage_key=request.storage_key,
                size_bytes=len(request.data),
                content_sha256=None,
                status="ready",
                reserved_at=request.created_at,
                ready_at=request.created_at,
                created_at=request.created_at,
            )
        )
        seed_session.commit()
    finally:
        seed_session.close()
    with artifact_storage.publish_verified_artifact(
        request.job_id,
        request.export_artifact_id,
        request.storage_key,
        request.file_type,
        request.data,
    ):
        pass

    result = ArtifactPersistenceService(
        artifact_storage,
        _artifact_repository_factory(db_session_factory),
    ).persist(request)

    verification_session = db_session_factory()
    try:
        row = verification_session.get(ExportArtifactRow, ARTIFACT_ID)
        assert row is not None
        assert row.status == "ready"
        assert row.content_sha256 == result.content_sha256
        assert result.created is False
    finally:
        verification_session.close()


def test_identical_pending_reservation_refreshes_activity_timestamp(
    db_session: Session,
) -> None:
    _create_job(db_session)
    repository = VerificationRepository(db_session)
    repository.save_result(JOB_ID, _result())
    repository.commit()
    request = _artifact_request(data=b"pending")
    content_sha256 = sha256(request.data).hexdigest()
    first_reserved_at = CREATED_AT + timedelta(minutes=1)
    second_reserved_at = CREATED_AT + timedelta(minutes=2)

    repository.reserve_export_artifact(
        export_artifact_id=request.export_artifact_id,
        verification_run_id=request.verification_run_id,
        review_revision_id=request.review_revision_id,
        source_version=request.source_version,
        file_type=request.file_type,
        file_name=request.file_name,
        media_type=request.media_type,
        storage_key=request.storage_key,
        size_bytes=len(request.data),
        content_sha256=content_sha256,
        reserved_at=first_reserved_at,
        created_at=request.created_at,
    )
    repository.commit()
    reservation = repository.reserve_export_artifact(
        export_artifact_id=request.export_artifact_id,
        verification_run_id=request.verification_run_id,
        review_revision_id=request.review_revision_id,
        source_version=request.source_version,
        file_type=request.file_type,
        file_name=request.file_name,
        media_type=request.media_type,
        storage_key=request.storage_key,
        size_bytes=len(request.data),
        content_sha256=content_sha256,
        reserved_at=second_reserved_at,
        created_at=request.created_at,
    )
    repository.commit()

    assert reservation.status is ArtifactLifecycleStatus.PENDING
    assert reservation.reserved_at == second_reserved_at


def test_postgres_finalize_and_reserve_follow_same_lock_order_without_deadlock(
    db_session_factory: sessionmaker[Session],
) -> None:
    seed_session = db_session_factory()
    try:
        _create_job(seed_session)
        verification_repository = VerificationRepository(seed_session)
        verification_repository.save_result(JOB_ID, _result())
        verification_repository.commit()
        jobs = JobRepository(seed_session)
        jobs.transition(JOB_ID, JobStatus.COMPLETED, 100, "处理完成")
        jobs.commit()
        request = _artifact_request(data=b"pending")
        reservation = verification_repository.reserve_export_artifact(
            export_artifact_id=request.export_artifact_id,
            verification_run_id=request.verification_run_id,
            review_revision_id=request.review_revision_id,
            source_version=request.source_version,
            file_type=request.file_type,
            file_name=request.file_name,
            media_type=request.media_type,
            storage_key=request.storage_key,
            size_bytes=len(request.data),
            content_sha256=sha256(request.data).hexdigest(),
            reserved_at=request.created_at,
            created_at=request.created_at,
        )
        verification_repository.commit()
    finally:
        seed_session.close()

    run_locked = Event()
    allow_job_lock = Event()
    finalizer_pid_ready = Event()
    finalizer_pid: list[int] = []

    def reserve_side() -> None:
        session = db_session_factory()
        try:
            session.execute(text("SET lock_timeout = '4s'"))
            session.execute(
                select(VerificationRunRow)
                .where(VerificationRunRow.verification_run_id == RUN_ID)
                .with_for_update()
            ).scalar_one()
            run_locked.set()
            if not allow_job_lock.wait(timeout=5):
                raise TimeoutError("timed out waiting to attempt the job lock")
            session.execute(
                select(JobRow)
                .where(JobRow.job_id == JOB_ID)
                .with_for_update()
            ).scalar_one()
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def finalize_side() -> ArtifactLifecycleStatus:
        session = db_session_factory()
        repository = VerificationRepository(session)
        try:
            session.execute(text("SET lock_timeout = '4s'"))
            finalizer_pid.append(
                int(session.execute(text("SELECT pg_backend_pid()")).scalar_one())
            )
            finalizer_pid_ready.set()
            snapshot = repository.finalize_export_artifact(
                reservation,
                ready_at=CREATED_AT + timedelta(minutes=1),
                consistency_check=lambda: None,
                require_current_result=True,
            )
            repository.commit()
            assert snapshot is not None
            return snapshot.status
        except Exception:
            repository.rollback()
            raise
        finally:
            session.close()

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            reserve_future = executor.submit(reserve_side)
            assert run_locked.wait(timeout=2)
            finalize_future = executor.submit(finalize_side)
            assert finalizer_pid_ready.wait(timeout=2)
            _wait_until_backend_waits_for_lock(
                db_session_factory,
                finalizer_pid[0],
            )
            allow_job_lock.set()
            reserve_future.result(timeout=6)
            assert (
                finalize_future.result(timeout=6)
                is ArtifactLifecycleStatus.READY
            )
    finally:
        allow_job_lock.set()


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
    artifact_storage: JobStorage,
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
    repository.commit()
    _artifact_service_for_session(artifact_storage, db_session).persist(
        _artifact_request(data=b"x" * 10)
    )

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


def test_concurrent_persist_review_revisions_allocate_unique_sequential_numbers(
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
    first_draft = ReviewRevisionDraft(
        revision_id=REVISION_ID,
        document_id=DOCUMENT_ID,
        verification_run_id=RUN_ID,
        source_version="sha256:source-v7",
        parent_revision_id=None,
        kind=DocumentRevisionKind.REVIEW,
        text="first",
    )
    second_draft = ReviewRevisionDraft(
        revision_id=SECOND_REVISION_ID,
        document_id=DOCUMENT_ID,
        verification_run_id=RUN_ID,
        source_version="sha256:source-v7",
        parent_revision_id=REVISION_ID,
        kind=DocumentRevisionKind.MANUAL,
        text="second",
    )

    def first_worker() -> PersistedDocumentRevision:
        session = db_session_factory()
        repository = VerificationRepository(session)
        try:
            session.execute(text("SET lock_timeout = '4s'"))
            persisted = repository.persist_review_revision(
                JOB_ID,
                first_draft,
                created_at=CREATED_AT,
            )
            first_saved.set()
            if not allow_first_commit.wait(timeout=2):
                raise TimeoutError("timed out waiting to commit first revision")
            repository.commit()
            return persisted
        finally:
            session.close()

    def second_worker() -> PersistedDocumentRevision:
        session = db_session_factory()
        repository = VerificationRepository(session)
        try:
            session.execute(text("SET lock_timeout = '4s'"))
            second_started.set()
            persisted = repository.persist_review_revision(
                JOB_ID,
                second_draft,
                created_at=CREATED_AT + timedelta(minutes=1),
            )
            repository.commit()
            return persisted
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
        first = first_future.result(timeout=5)
        second = second_future.result(timeout=5)

    assert (first.revision_number, second.revision_number) == (1, 2)
    assert second.parent_revision_id == first.revision_id


def test_concurrent_persist_review_revision_uuid_retry_is_idempotent(
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
    draft = ReviewRevisionDraft(
        revision_id=REVISION_ID,
        document_id=DOCUMENT_ID,
        verification_run_id=RUN_ID,
        source_version="sha256:source-v7",
        parent_revision_id=None,
        kind=DocumentRevisionKind.REVIEW,
        text="same",
    )

    def worker(
        created_at: datetime,
        hold: bool,
        *,
        second: bool = False,
    ) -> PersistedDocumentRevision:
        session = db_session_factory()
        repository = VerificationRepository(session)
        try:
            session.execute(text("SET lock_timeout = '4s'"))
            if second:
                second_started.set()
            persisted = repository.persist_review_revision(
                JOB_ID,
                draft,
                created_at=created_at,
            )
            if hold:
                first_saved.set()
                if not allow_first_commit.wait(timeout=2):
                    raise TimeoutError("timed out waiting to commit retry")
            repository.commit()
            return persisted
        finally:
            if second:
                second_finished.set()
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(worker, CREATED_AT, True)
        assert first_saved.wait(timeout=2)
        retry_future = executor.submit(
            worker,
            CREATED_AT + timedelta(minutes=1),
            False,
            second=True,
        )
        assert second_started.wait(timeout=1)
        assert not second_finished.wait(timeout=0.2)
        allow_first_commit.set()
        first = first_future.result(timeout=5)
        retried = retry_future.result(timeout=5)

    assert retried == first
    assert retried.revision_number == 1
    assert retried.created_at == CREATED_AT


@pytest.mark.parametrize(
    ("second_revision_id", "second_text", "expected_message"),
    [
        (SECOND_REVISION_ID, "stale", "latest persisted revision"),
        (REVISION_ID, "collision", "different data"),
    ],
)
def test_concurrent_persist_review_revision_rejects_stale_parent_or_uuid_collision(
    db_session_factory: sessionmaker[Session],
    second_revision_id: UUID,
    second_text: str,
    expected_message: str,
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
            repository.persist_review_revision(
                JOB_ID,
                ReviewRevisionDraft(
                    revision_id=REVISION_ID,
                    document_id=DOCUMENT_ID,
                    verification_run_id=RUN_ID,
                    source_version="sha256:source-v7",
                    parent_revision_id=None,
                    kind=DocumentRevisionKind.REVIEW,
                    text="first",
                ),
                created_at=CREATED_AT,
            )
            first_saved.set()
            if not allow_first_commit.wait(timeout=2):
                raise TimeoutError("timed out waiting to commit conflict")
            repository.commit()
        finally:
            session.close()

    def second_worker() -> Exception | None:
        session = db_session_factory()
        repository = VerificationRepository(session)
        try:
            session.execute(text("SET lock_timeout = '4s'"))
            second_started.set()
            repository.persist_review_revision(
                JOB_ID,
                ReviewRevisionDraft(
                    revision_id=second_revision_id,
                    document_id=DOCUMENT_ID,
                    verification_run_id=RUN_ID,
                    source_version="sha256:source-v7",
                    parent_revision_id=None,
                    kind=DocumentRevisionKind.MANUAL,
                    text=second_text,
                ),
                created_at=CREATED_AT + timedelta(minutes=1),
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
    assert expected_message in str(error)
    assert not isinstance(error, IntegrityError)


def test_concurrent_identical_artifact_service_retries_succeed(
    db_session_factory: sessionmaker[Session],
    artifact_storage: JobStorage,
) -> None:
    seed_session = db_session_factory()
    try:
        _create_job(seed_session)
        repository = VerificationRepository(seed_session)
        repository.save_result(JOB_ID, _result())
        repository.commit()
    finally:
        seed_session.close()

    request = _artifact_request(data=b"x" * 10)
    start = Event()

    def worker() -> ArtifactPersistenceResult:
        if not start.wait(timeout=2):
            raise TimeoutError("timed out waiting to start artifact persistence")
        return ArtifactPersistenceService(
            artifact_storage,
            _artifact_repository_factory(db_session_factory),
        ).persist(request)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker) for _ in range(2)]
        start.set()
        results = [future.result(timeout=5) for future in futures]

    assert sorted(result.created for result in results) == [False, True]
    verification_session = db_session_factory()
    try:
        assert verification_session.scalar(
            select(func.count()).select_from(ExportArtifactRow)
        ) == 1
    finally:
        verification_session.close()


def test_concurrent_conflicting_artifact_service_rejects_one_writer(
    db_session_factory: sessionmaker[Session],
    artifact_storage: JobStorage,
) -> None:
    seed_session = db_session_factory()
    try:
        _create_job(seed_session)
        repository = VerificationRepository(seed_session)
        repository.save_result(JOB_ID, _result())
        repository.commit()
    finally:
        seed_session.close()

    requests = (
        _artifact_request(data=b"first"),
        _artifact_request(data=b"other"),
    )
    start = Event()

    def worker(request: ArtifactPersistenceRequest):
        if not start.wait(timeout=2):
            raise TimeoutError("timed out waiting to start artifact persistence")
        try:
            return ArtifactPersistenceService(
                artifact_storage,
                _artifact_repository_factory(db_session_factory),
            ).persist(request)
        except Exception as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker, request) for request in requests]
        start.set()
        outcomes = [future.result(timeout=5) for future in futures]

    successes = [
        outcome for outcome in outcomes if isinstance(outcome, ArtifactPersistenceResult)
    ]
    failures = [outcome for outcome in outcomes if isinstance(outcome, Exception)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], ValueError)
    assert "different content" in str(failures[0])
    successful_data = next(
        request.data
        for request in requests
        if sha256(request.data).hexdigest() == successes[0].content_sha256
    )
    assert successes[0].path.read_bytes() == successful_data


def test_postgres_orphan_cleanup_waits_for_committed_pending_reservation(
    db_session_factory: sessionmaker[Session],
    artifact_storage: JobStorage,
) -> None:
    job_id = uuid4()
    run_id = uuid4()
    request = _artifact_request(
        job_id=job_id,
        artifact_id=uuid4(),
        verification_run_id=run_id,
        data=b"reserved before cleanup",
    )
    seed_session = db_session_factory()
    try:
        _create_job(seed_session, job_id=job_id)
        repository = VerificationRepository(seed_session)
        repository.save_result(
            job_id,
            _result(
                document_id=uuid4(),
                verification_run_id=run_id,
                issue_id=uuid4(),
            ),
        )
        repository.commit()
    finally:
        seed_session.close()

    with artifact_storage.publish_verified_artifact(
        request.job_id,
        request.export_artifact_id,
        request.storage_key,
        request.file_type,
        request.data,
    ) as handle:
        artifact_path = handle.path
    cutoff = CREATED_AT + timedelta(hours=1)
    stale_timestamp = (cutoff - timedelta(seconds=1)).timestamp()
    os.utime(artifact_path, (stale_timestamp, stale_timestamp))
    (candidate,) = artifact_storage.discover_stale_orphaned_artifacts(cutoff)

    reservation_written = Event()
    allow_reservation_commit = Event()
    cleanup_started = Event()
    cleanup_finished = Event()

    def reserve() -> None:
        session = db_session_factory()
        repository = VerificationRepository(session)
        try:
            session.execute(text("SET lock_timeout = '4s'"))
            repository.reserve_export_artifact(
                export_artifact_id=request.export_artifact_id,
                verification_run_id=request.verification_run_id,
                review_revision_id=request.review_revision_id,
                source_version=request.source_version,
                file_type=request.file_type,
                file_name=request.file_name,
                media_type=request.media_type,
                storage_key=request.storage_key,
                size_bytes=len(request.data),
                content_sha256=sha256(request.data).hexdigest(),
                reserved_at=request.created_at,
                created_at=request.created_at,
            )
            reservation_written.set()
            if not allow_reservation_commit.wait(timeout=2):
                raise TimeoutError("timed out waiting to commit pending reservation")
            repository.commit()
        except Exception:
            repository.rollback()
            raise
        finally:
            session.close()

    def cleanup() -> bool:
        session = db_session_factory()
        repository = VerificationRepository(session)
        try:
            session.execute(text("SET lock_timeout = '4s'"))
            cleanup_started.set()
            deleted = repository.delete_unreferenced_artifact(
                job_id=candidate.job_id,
                artifact_id=candidate.artifact_id,
                file_type=candidate.file_type,
                storage_key=candidate.storage_key,
                candidate_storage_key=candidate.path_storage_key,
                delete_path=lambda prune_empty_directories: (
                    artifact_storage.delete_stale_orphaned_artifact(
                        candidate,
                        cutoff,
                        prune_empty_directories=prune_empty_directories,
                    )
                ),
            )
            repository.commit()
            return deleted
        except Exception:
            repository.rollback()
            raise
        finally:
            cleanup_finished.set()
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        reservation_future = executor.submit(reserve)
        assert reservation_written.wait(timeout=2)
        cleanup_future = executor.submit(cleanup)
        assert cleanup_started.wait(timeout=1)
        assert not cleanup_finished.wait(timeout=0.2)
        allow_reservation_commit.set()
        reservation_future.result(timeout=5)
        assert cleanup_future.result(timeout=5) is False

    assert artifact_path.read_bytes() == request.data
    verification_session = db_session_factory()
    try:
        row = verification_session.get(ExportArtifactRow, request.export_artifact_id)
        assert row is not None
        assert row.status == ArtifactLifecycleStatus.PENDING.value
    finally:
        verification_session.close()


def test_postgres_cleanup_protects_pending_repair_quarantine_until_ready(
    db_session_factory: sessionmaker[Session],
    artifact_storage: JobStorage,
) -> None:
    job_id = uuid4()
    run_id = uuid4()
    request = _artifact_request(
        job_id=job_id,
        artifact_id=uuid4(),
        verification_run_id=run_id,
        data=b"repair-content",
    )
    seed_session = db_session_factory()
    try:
        _create_job(seed_session, job_id=job_id)
        repository = VerificationRepository(seed_session)
        repository.save_result(
            job_id,
            _result(
                document_id=uuid4(),
                verification_run_id=run_id,
                issue_id=uuid4(),
            ),
        )
        repository.commit()
        jobs = JobRepository(seed_session)
        jobs.transition(job_id, JobStatus.COMPLETED, 100, "处理完成")
        jobs.commit()
    finally:
        seed_session.close()

    persisted = ArtifactPersistenceService(
        artifact_storage,
        _artifact_repository_factory(db_session_factory),
    ).persist(request)
    persisted.path.write_bytes(b"corrupt")
    digest = sha256(request.data).hexdigest()
    expected = ArtifactReservation(
        export_artifact_id=request.export_artifact_id,
        job_id=request.job_id,
        verification_run_id=request.verification_run_id,
        review_revision_id=request.review_revision_id,
        source_version=request.source_version,
        file_type=request.file_type,
        file_name=request.file_name,
        media_type=request.media_type,
        storage_key=request.storage_key,
        size_bytes=len(request.data),
        content_sha256=digest,
        status=ArtifactLifecycleStatus.PENDING,
        reserved_at=CREATED_AT + timedelta(minutes=1),
        created_at=request.created_at,
    )
    repair_session = db_session_factory()
    try:
        repository = VerificationRepository(repair_session)
        reservation = repository.begin_export_artifact_repair(
            expected,
            consistency_check=lambda: artifact_storage.prepare_artifact_repair(
                request.job_id,
                request.export_artifact_id,
                request.storage_key,
                request.file_type,
                expected_size=len(request.data),
                expected_digest=digest,
            ),
        )
        repository.commit()
        assert reservation is not None
        assert reservation.status is ArtifactLifecycleStatus.PENDING
    finally:
        repair_session.close()

    quarantine = artifact_storage.artifact_repair_quarantine_path(
        request.job_id,
        request.export_artifact_id,
        request.file_type,
    )
    cutoff = datetime.now(UTC) + timedelta(hours=1)
    stale_timestamp = (cutoff - timedelta(seconds=1)).timestamp()
    os.utime(quarantine, (stale_timestamp, stale_timestamp))
    candidate = next(
        candidate
        for candidate in artifact_storage.discover_stale_orphaned_artifacts(cutoff)
        if candidate.path_storage_key.endswith(".repair-corrupt")
    )
    pending_cleanup_session = db_session_factory()
    try:
        repository = VerificationRepository(pending_cleanup_session)
        deleted = repository.delete_unreferenced_artifact(
            job_id=candidate.job_id,
            artifact_id=candidate.artifact_id,
            file_type=candidate.file_type,
            storage_key=candidate.storage_key,
            candidate_storage_key=candidate.path_storage_key,
            delete_path=lambda prune: artifact_storage.delete_stale_orphaned_artifact(
                candidate,
                cutoff,
                prune_empty_directories=prune,
            ),
        )
        repository.commit()
    finally:
        pending_cleanup_session.close()
    assert deleted is False
    assert quarantine.exists()

    ArtifactPersistenceService(
        artifact_storage,
        _artifact_repository_factory(db_session_factory),
    ).persist(request)
    ready_cleanup_session = db_session_factory()
    try:
        repository = VerificationRepository(ready_cleanup_session)
        deleted = repository.delete_unreferenced_artifact(
            job_id=candidate.job_id,
            artifact_id=candidate.artifact_id,
            file_type=candidate.file_type,
            storage_key=candidate.storage_key,
            candidate_storage_key=candidate.path_storage_key,
            delete_path=lambda prune: artifact_storage.delete_stale_orphaned_artifact(
                candidate,
                cutoff,
                prune_empty_directories=prune,
            ),
        )
        repository.commit()
    finally:
        ready_cleanup_session.close()
    assert deleted is True
    assert not quarantine.exists()


def test_postgres_orphan_cleanup_deletes_before_reservation_then_publication(
    db_session_factory: sessionmaker[Session],
    artifact_storage: JobStorage,
) -> None:
    job_id = uuid4()
    run_id = uuid4()
    request = _artifact_request(
        job_id=job_id,
        artifact_id=uuid4(),
        verification_run_id=run_id,
        data=b"cleanup before reservation",
    )
    seed_session = db_session_factory()
    try:
        _create_job(seed_session, job_id=job_id)
        repository = VerificationRepository(seed_session)
        repository.save_result(
            job_id,
            _result(
                document_id=uuid4(),
                verification_run_id=run_id,
                issue_id=uuid4(),
            ),
        )
        repository.commit()
    finally:
        seed_session.close()

    with artifact_storage.publish_verified_artifact(
        request.job_id,
        request.export_artifact_id,
        request.storage_key,
        request.file_type,
        request.data,
    ) as handle:
        artifact_path = handle.path
    cutoff = CREATED_AT + timedelta(hours=1)
    stale_timestamp = (cutoff - timedelta(seconds=1)).timestamp()
    os.utime(artifact_path, (stale_timestamp, stale_timestamp))
    (candidate,) = artifact_storage.discover_stale_orphaned_artifacts(cutoff)

    cleanup_locked_job = Event()
    allow_cleanup_delete = Event()
    publication_started = Event()
    publication_finished = Event()

    def cleanup() -> bool:
        session = db_session_factory()
        repository = VerificationRepository(session)
        try:
            session.execute(text("SET lock_timeout = '4s'"))

            def delete_path(prune_empty_directories: bool) -> bool:
                cleanup_locked_job.set()
                if not allow_cleanup_delete.wait(timeout=2):
                    raise TimeoutError("timed out waiting to delete stale artifact")
                return artifact_storage.delete_stale_orphaned_artifact(
                    candidate,
                    cutoff,
                    prune_empty_directories=prune_empty_directories,
                )

            deleted = repository.delete_unreferenced_artifact(
                job_id=candidate.job_id,
                artifact_id=candidate.artifact_id,
                file_type=candidate.file_type,
                storage_key=candidate.storage_key,
                candidate_storage_key=candidate.path_storage_key,
                delete_path=delete_path,
            )
            repository.commit()
            return deleted
        except Exception:
            repository.rollback()
            raise
        finally:
            session.close()

    def publish() -> ArtifactPersistenceResult:
        publication_started.set()
        try:
            return ArtifactPersistenceService(
                artifact_storage,
                _artifact_repository_factory(db_session_factory),
            ).persist(request)
        finally:
            publication_finished.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        cleanup_future = executor.submit(cleanup)
        assert cleanup_locked_job.wait(timeout=2)
        publication_future = executor.submit(publish)
        assert publication_started.wait(timeout=1)
        assert not publication_finished.wait(timeout=0.2)
        allow_cleanup_delete.set()
        assert cleanup_future.result(timeout=5) is True
        published = publication_future.result(timeout=5)

    assert published.created is True
    assert artifact_path.read_bytes() == request.data
    verification_session = db_session_factory()
    try:
        row = verification_session.get(ExportArtifactRow, request.export_artifact_id)
        assert row is not None
        assert row.status == ArtifactLifecycleStatus.READY.value
    finally:
        verification_session.close()


def test_postgres_stale_reconciliation_skips_row_refreshed_after_listing(
    db_session_factory: sessionmaker[Session],
    artifact_storage: JobStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = uuid4()
    run_id = uuid4()
    request = _artifact_request(
        job_id=job_id,
        artifact_id=uuid4(),
        verification_run_id=run_id,
        data=b"refreshed after stale listing",
    )
    initial_reserved_at = CREATED_AT
    refreshed_reserved_at = CREATED_AT + timedelta(hours=1)
    cutoff = CREATED_AT + timedelta(minutes=30)
    seed_session = db_session_factory()
    try:
        _create_job(seed_session, job_id=job_id)
        repository = VerificationRepository(seed_session)
        repository.save_result(
            job_id,
            _result(
                document_id=uuid4(),
                verification_run_id=run_id,
                issue_id=uuid4(),
            ),
        )
        repository.reserve_export_artifact(
            export_artifact_id=request.export_artifact_id,
            verification_run_id=request.verification_run_id,
            review_revision_id=request.review_revision_id,
            source_version=request.source_version,
            file_type=request.file_type,
            file_name=request.file_name,
            media_type=request.media_type,
            storage_key=request.storage_key,
            size_bytes=len(request.data),
            content_sha256=sha256(request.data).hexdigest(),
            reserved_at=initial_reserved_at,
            created_at=request.created_at,
        )
        repository.commit()
    finally:
        seed_session.close()

    missing_file_opened = Event()
    allow_missing_result = Event()
    original_open_verified = artifact_storage.open_verified_artifact

    def open_verified_after_refresh(*args, **kwargs):
        missing_file_opened.set()
        if not allow_missing_result.wait(timeout=2):
            raise TimeoutError("timed out waiting to refresh pending reservation")
        return original_open_verified(*args, **kwargs)

    monkeypatch.setattr(
        artifact_storage,
        "open_verified_artifact",
        open_verified_after_refresh,
    )

    with ThreadPoolExecutor(max_workers=1) as executor:
        reconciliation_future = executor.submit(
            ArtifactPendingReconciliationService(
                artifact_storage,
                _artifact_repository_factory(db_session_factory),
            ).reconcile_before,
            cutoff,
        )
        assert missing_file_opened.wait(timeout=2)
        refresh_session = db_session_factory()
        try:
            refreshed = VerificationRepository(refresh_session).reserve_export_artifact(
                export_artifact_id=request.export_artifact_id,
                verification_run_id=request.verification_run_id,
                review_revision_id=request.review_revision_id,
                source_version=request.source_version,
                file_type=request.file_type,
                file_name=request.file_name,
                media_type=request.media_type,
                storage_key=request.storage_key,
                size_bytes=len(request.data),
                content_sha256=sha256(request.data).hexdigest(),
                reserved_at=refreshed_reserved_at,
                created_at=request.created_at,
            )
            refresh_session.commit()
        finally:
            refresh_session.close()
        allow_missing_result.set()
        reconciliation = reconciliation_future.result(timeout=5)

    assert refreshed.reserved_at == refreshed_reserved_at
    assert reconciliation.deleted_artifact_ids == ()
    assert reconciliation.ready_artifact_ids == ()
    assert reconciliation.deferred_artifact_ids == ()
    verification_session = db_session_factory()
    try:
        row = verification_session.get(ExportArtifactRow, request.export_artifact_id)
        assert row is not None
        assert row.status == ArtifactLifecycleStatus.PENDING.value
        assert row.reserved_at == refreshed_reserved_at
    finally:
        verification_session.close()


def test_get_result_for_job_returns_none_when_job_has_no_run(db_session: Session) -> None:
    _create_job(db_session)

    assert VerificationRepository(db_session).get_result_for_job(JOB_ID) is None


def _artifact_repository_factory(
    session_factory: sessionmaker[Session],
):
    @contextmanager
    def factory() -> Iterator[VerificationRepository]:
        session = session_factory()
        try:
            yield VerificationRepository(session)
        finally:
            session.close()

    return factory


def _artifact_service_for_session(
    storage: JobStorage,
    session: Session,
) -> ArtifactPersistenceService:
    session_factory = sessionmaker(
        bind=session.get_bind(),
        autoflush=False,
        expire_on_commit=False,
    )
    return ArtifactPersistenceService(
        storage,
        _artifact_repository_factory(session_factory),
    )


def _artifact_request(
    *,
    job_id: UUID = JOB_ID,
    artifact_id: UUID = ARTIFACT_ID,
    verification_run_id: UUID = RUN_ID,
    review_revision_id: UUID | None = None,
    source_version: str = "sha256:source-v7",
    file_type: FileType = FileType.DOCX,
    file_name: str = "sample.docx",
    media_type: str = "application/octet-stream",
    data: bytes,
    created_at: datetime = CREATED_AT,
) -> ArtifactPersistenceRequest:
    storage_key = build_artifact_storage_key(job_id, artifact_id, file_type)
    return ArtifactPersistenceRequest(
        job_id=job_id,
        export_artifact_id=artifact_id,
        verification_run_id=verification_run_id,
        review_revision_id=review_revision_id,
        source_version=source_version,
        file_type=file_type,
        file_name=file_name,
        media_type=media_type,
        storage_key=storage_key,
        data=data,
        created_at=created_at,
    )


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


def _wait_until_backend_waits_for_lock(
    db_session_factory: sessionmaker[Session],
    backend_pid: int,
    *,
    timeout_seconds: float = 3.0,
) -> None:
    deadline = monotonic() + timeout_seconds
    poll_wait = Event()
    session = db_session_factory()
    try:
        while monotonic() < deadline:
            wait_event_type = session.execute(
                text(
                    "SELECT wait_event_type FROM pg_stat_activity "
                    "WHERE pid = :backend_pid"
                ),
                {"backend_pid": backend_pid},
            ).scalar_one_or_none()
            if wait_event_type == "Lock":
                return
            poll_wait.wait(timeout=0.02)
    finally:
        session.close()
    raise TimeoutError(f"backend {backend_pid} did not wait for a lock")


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
        block_start=0,
        block_end=2,
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
