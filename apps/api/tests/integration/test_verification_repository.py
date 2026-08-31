from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import Engine, inspect, select
from sqlalchemy.engine.reflection import Inspector
from sqlalchemy.orm import Session

from text_verification.domain.documents import FileType
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
from text_verification.infrastructure.orm import ExportArtifactRow, ReviewRevisionRow
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


def test_database_schema_contains_normalized_verification_tables(db_engine: Engine) -> None:
    inspector = inspect(db_engine)
    table_names = set(inspector.get_table_names())

    assert {
        "documents",
        "verification_runs",
        "verification_issues",
        "review_revisions",
        "export_artifacts",
    } <= table_names
    assert {"uq_documents_job", "uq_documents_identity"} <= _unique_names(
        inspector, "documents"
    )
    assert {"uq_verification_runs_job"} <= _unique_names(inspector, "verification_runs")
    assert {
        "uq_verification_issues_run_issue",
        "uq_verification_issues_run_index",
    } <= _unique_names(
        inspector, "verification_issues"
    )
    assert {"uq_review_revisions_run_number"} <= _unique_names(
        inspector, "review_revisions"
    )
    assert {"uq_export_artifacts_storage_key"} <= _unique_names(
        inspector, "export_artifacts"
    )
    assert ("jobs", ("job_id",), "CASCADE") in _foreign_keys(inspector, "documents")
    assert ("jobs", ("job_id",), "CASCADE") in _foreign_keys(
        inspector, "verification_runs"
    )
    assert ("documents", ("document_id",), "CASCADE") in _foreign_keys(
        inspector, "verification_runs"
    )
    assert ("verification_runs", ("verification_run_id",), "CASCADE") in _foreign_keys(
        inspector, "verification_issues"
    )
    assert ("documents", ("document_id",), "CASCADE") in _foreign_keys(
        inspector, "verification_issues"
    )
    assert ("verification_runs", ("verification_run_id",), "CASCADE") in _foreign_keys(
        inspector, "review_revisions"
    )
    assert ("documents", ("document_id",), "CASCADE") in _foreign_keys(
        inspector, "review_revisions"
    )
    assert ("verification_runs", ("verification_run_id",), "CASCADE") in _foreign_keys(
        inspector, "export_artifacts"
    )
    assert (
        "review_revisions",
        ("review_revision_id",),
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


def test_save_result_is_idempotent_for_same_job_and_run(db_session: Session) -> None:
    _create_job(db_session)
    repository = VerificationRepository(db_session)
    result = _result()

    repository.save_result(JOB_ID, result)
    repository.commit()
    repository.save_result(JOB_ID, result)
    repository.commit()

    assert repository.get_result_for_job(JOB_ID) == result


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


def test_get_result_for_job_returns_none_when_job_has_no_run(db_session: Session) -> None:
    _create_job(db_session)

    assert VerificationRepository(db_session).get_result_for_job(JOB_ID) is None


def _create_job(db_session: Session) -> None:
    repository = JobRepository(db_session)
    repository.create_job(
        job_id=JOB_ID,
        source_name="sample.docx",
        file_type=FileType.DOCX.value,
        size_bytes=4096,
        storage_key=str(JOB_ID),
        created_at=CREATED_AT,
        expires_at=CREATED_AT + timedelta(days=1),
    )
    repository.commit()


def _result() -> VerificationResult:
    issue = Issue(
        issue_id=ISSUE_ID,
        document_id=DOCUMENT_ID,
        verification_run_id=RUN_ID,
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
        verification_run_id=RUN_ID,
        document_id=DOCUMENT_ID,
        source_version="sha256:source-v7",
        source_name="sample.docx",
        file_type=FileType.DOCX,
        scenario=Scenario.BUSINESS,
        text="帐号测试\n第二行",
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


def _unique_names(inspector: Inspector, table_name: str) -> set[str | None]:
    return {
        constraint["name"]
        for constraint in inspector.get_unique_constraints(table_name)
    }


def _foreign_keys(
    inspector: Inspector,
    table_name: str,
) -> set[tuple[str, tuple[str, ...], str | None]]:
    return {
        (
            foreign_key["referred_table"],
            tuple(foreign_key["constrained_columns"]),
            foreign_key["options"].get("ondelete"),
        )
        for foreign_key in inspector.get_foreign_keys(table_name)
    }
