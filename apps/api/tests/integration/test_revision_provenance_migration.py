from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from uuid import UUID

from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from alembic import command
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
from text_verification.infrastructure.repositories import JobRepository
from text_verification.infrastructure.verification_repository import (
    VerificationRepository,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DERIVATION_ISSUE_INDEX = "ix_verification_issues_run_start_end_issue_index"


def test_upgrade_from_pre_0012_backfills_only_provable_revision_provenance(
    db_engine,
    alembic_config,
) -> None:
    created_at = datetime(2026, 9, 4, 2, 0, tzinfo=UTC)
    fixtures = [
        {
            "job_id": UUID("10000000-0000-4000-8000-000000000101"),
            "run_id": UUID("30000000-0000-4000-8000-000000000101"),
            "issue_id": UUID("40000000-0000-4000-8000-000000000101"),
            "revision_id": UUID("50000000-0000-4000-8000-000000000101"),
            "artifact_id": None,
            "kind": "review",
            "revision_text": "账号测试",
            "artifact_status": None,
        },
        {
            "job_id": UUID("10000000-0000-4000-8000-000000000102"),
            "run_id": UUID("30000000-0000-4000-8000-000000000102"),
            "issue_id": UUID("40000000-0000-4000-8000-000000000102"),
            "revision_id": UUID("50000000-0000-4000-8000-000000000102"),
            "artifact_id": UUID("60000000-0000-4000-8000-000000000102"),
            "kind": "manual",
            "revision_text": "已生成的旧手工修订",
            "artifact_status": "ready",
        },
        {
            "job_id": UUID("10000000-0000-4000-8000-000000000103"),
            "run_id": UUID("30000000-0000-4000-8000-000000000103"),
            "issue_id": UUID("40000000-0000-4000-8000-000000000103"),
            "revision_id": UUID("50000000-0000-4000-8000-000000000103"),
            "artifact_id": UUID("60000000-0000-4000-8000-000000000103"),
            "kind": "manual",
            "revision_text": "未完成的旧手工修订",
            "artifact_status": "pending",
        },
    ]

    try:
        command.downgrade(
            alembic_config,
            "0011_add_artifact_reservation_version",
        )
        session = Session(db_engine)
        try:
            for fixture in fixtures:
                _create_job_and_result(
                    session,
                    fixture["job_id"],
                    fixture["run_id"],
                    fixture["issue_id"],
                    created_at,
                )
            session.commit()
        finally:
            session.close()

        with db_engine.begin() as connection:
            for fixture in fixtures:
                connection.execute(
                    text(
                        "INSERT INTO review_revisions ("
                        "review_revision_id, verification_run_id, document_id, "
                        "source_version, revision_number, parent_revision_id, "
                        "kind, text, created_at"
                        ") VALUES ("
                        ":revision_id, :run_id, :job_id, :source_version, 1, "
                        "NULL, :kind, :revision_text, :created_at"
                        ")"
                    ),
                    {
                        **fixture,
                        "source_version": "sha256:source",
                        "created_at": created_at,
                    },
                )
                if fixture["artifact_id"] is None:
                    continue
                status = fixture["artifact_status"]
                connection.execute(
                    text(
                        "INSERT INTO export_artifacts ("
                        "export_artifact_id, verification_run_id, review_revision_id, "
                        "source_version, file_type, file_name, media_type, storage_key, "
                        "size_bytes, content_sha256, status, reserved_at, "
                        "reservation_version, ready_at, created_at"
                        ") VALUES ("
                        ":artifact_id, :run_id, :revision_id, :source_version, "
                        "'txt', 'legacy.txt', 'text/plain', :storage_key, 6, "
                        ":content_sha256, :status, :created_at, 0, :ready_at, :created_at"
                        ")"
                    ),
                    {
                        **fixture,
                        "source_version": "sha256:source",
                        "storage_key": (
                            f"{fixture['job_id']}/exports/"
                            f"{fixture['artifact_id']}.txt"
                        ),
                        "content_sha256": "a" * 64,
                        "status": status,
                        "ready_at": created_at if status == "ready" else None,
                        "created_at": created_at,
                    },
                )

        command.upgrade(alembic_config, "head")

        with db_engine.connect() as connection:
            rows = {
                row.review_revision_id: row
                for row in connection.execute(
                    text(
                        "SELECT review_revision_id, provenance_state, "
                        "verified_provenance "
                        "FROM review_revisions"
                    )
                ).mappings()
            }
            artifact_rows = {
                row.export_artifact_id: row.status
                for row in connection.execute(
                    text(
                        "SELECT export_artifact_id, status "
                        "FROM export_artifacts"
                    )
                ).mappings()
            }

        provable = rows[fixtures[0]["revision_id"]]
        assert provable.provenance_state == "verified"
        assert provable.verified_provenance["kind"] == "original_result"
        assert provable.verified_provenance["job_id"] == str(
            fixtures[0]["job_id"]
        )
        for fixture in fixtures[1:]:
            unavailable = rows[fixture["revision_id"]]
            assert unavailable.provenance_state == "legacy_unavailable"
            assert unavailable.verified_provenance is None
        assert artifact_rows[fixtures[1]["artifact_id"]] == "ready"
        assert artifact_rows[fixtures[2]["artifact_id"]] == "pending"

        command.downgrade(
            alembic_config,
            "0011_add_artifact_reservation_version",
        )
        columns = {
            column["name"]
            for column in inspect(db_engine).get_columns("review_revisions")
        }
        assert "verified_provenance" not in columns
        assert "provenance_state" not in columns
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


def test_postgres_0012_derivation_support_index_serves_ordered_issue_queries(
    db_engine,
    alembic_config,
) -> None:
    created_at = datetime(2026, 9, 4, 3, 0, tzinfo=UTC)
    job_id = UUID("10000000-0000-4000-8000-000000000201")
    run_id = UUID("30000000-0000-4000-8000-000000000201")
    issue_id = UUID("40000000-0000-4000-8000-000000000201")
    second_issue_id = UUID("40000000-0000-4000-8000-000000000202")
    revision_id = UUID("50000000-0000-4000-8000-000000000201")

    try:
        command.downgrade(
            alembic_config,
            "0011_add_artifact_reservation_version",
        )
        session = Session(db_engine)
        try:
            _create_job_and_result(session, job_id, run_id, issue_id, created_at)
            session.commit()
        finally:
            session.close()

        with db_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO verification_issues ("
                    "verification_run_id, document_id, issue_id, issue_index, "
                    "block_id, page, start, \"end\", block_start, block_end, "
                    "original, suggestion, alternatives, type, severity, layer, "
                    "message, description, rule_id, rule_version, source, "
                    "source_version, confidence, auto_fixable, context, review, "
                    "review_reason"
                    ") VALUES ("
                    ":run_id, :job_id, :issue_id, 1, 'p-0', NULL, 2, 4, 2, 4, "
                    "'测试', '测验', '[\"测试\"]'::jsonb, 'typo', 'warning', "
                    "'character', '疑似错别字', '疑似错别字', 'cn_typo_2', '1', "
                    "'legacy', '1', 0.8, true, '帐号测试', NULL, NULL"
                    ")"
                ),
                {
                    "run_id": run_id,
                    "job_id": job_id,
                    "issue_id": second_issue_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO review_revisions ("
                    "review_revision_id, verification_run_id, document_id, "
                    "source_version, revision_number, parent_revision_id, "
                    "kind, text, created_at"
                    ") VALUES ("
                    ":revision_id, :run_id, :job_id, 'sha256:source', 1, "
                    "NULL, 'review', '账号测试', :created_at"
                    ")"
                ),
                {
                    "revision_id": revision_id,
                    "run_id": run_id,
                    "job_id": job_id,
                    "created_at": created_at,
                },
            )
            connection.execute(text(_offline_upgrade_support_index_ddl()))
            connection.execute(text("SET LOCAL enable_seqscan = off"))
            ordered_plan = "\n".join(
                row[0]
                for row in connection.execute(
                    text(
                        'EXPLAIN (COSTS OFF) SELECT "end", suggestion, alternatives '
                        "FROM verification_issues "
                        "WHERE verification_run_id = :run_id AND start = 0 "
                        'ORDER BY "end", issue_index'
                    ),
                    {"run_id": run_id},
                )
            )
            next_start_plan = "\n".join(
                row[0]
                for row in connection.execute(
                    text(
                        "EXPLAIN (COSTS OFF) "
                        "SELECT COALESCE(min(start), 4) "
                        "FROM verification_issues "
                        "WHERE verification_run_id = :run_id AND start > 0"
                    ),
                    {"run_id": run_id},
                )
            )
            connection.execute(text(f"DROP INDEX {DERIVATION_ISSUE_INDEX}"))

        assert DERIVATION_ISSUE_INDEX in ordered_plan
        assert DERIVATION_ISSUE_INDEX in next_start_plan

        command.upgrade(alembic_config, "head")

        with db_engine.connect() as connection:
            provenance_row = connection.execute(
                text(
                    "SELECT provenance_state, verified_provenance "
                    "FROM review_revisions "
                    "WHERE review_revision_id = :revision_id"
                ),
                {"revision_id": revision_id},
            ).mappings().one()

        assert provenance_row.provenance_state == "verified"
        assert provenance_row.verified_provenance["kind"] == "original_result"
        assert DERIVATION_ISSUE_INDEX not in {
            index["name"]
            for index in inspect(db_engine).get_indexes("verification_issues")
        }
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


def test_offline_upgrade_support_index_ddl_preserves_storage_logger_state() -> None:
    logger = logging.getLogger("text_verification.infrastructure.storage")
    original_disabled = logger.disabled
    logger.disabled = False

    try:
        _offline_upgrade_support_index_ddl()
        assert logger.disabled is False
    finally:
        logger.disabled = original_disabled


def _offline_upgrade_support_index_ddl() -> str:
    output = StringIO()
    config = Config(output_buffer=output)
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.attributes["database_url"] = "postgresql://example/example"
    command.upgrade(
        config,
        "0011_add_artifact_reservation_version:0012_add_revision_provenance",
        sql=True,
    )
    for statement in output.getvalue().splitlines():
        if statement.startswith(f"CREATE INDEX {DERIVATION_ISSUE_INDEX} "):
            return statement
    raise AssertionError(f"Missing {DERIVATION_ISSUE_INDEX} DDL")


def _create_job_and_result(
    session: Session,
    job_id: UUID,
    run_id: UUID,
    issue_id: UUID,
    created_at: datetime,
) -> None:
    JobRepository(session).create_job(
        job_id=job_id,
        source_name="legacy.txt",
        file_type=FileType.TXT.value,
        size_bytes=8,
        storage_key=str(job_id),
        created_at=created_at,
        expires_at=created_at + timedelta(days=1),
    )
    result = VerificationResult(
        verification_run_id=run_id,
        document_id=job_id,
        source_version="sha256:source",
        source_name="legacy.txt",
        file_type=FileType.TXT,
        scenario=Scenario.GENERAL,
        text="帐号测试",
        blocks=(
            TextBlock(
                block_id="p-0",
                kind="paragraph",
                text="帐号测试",
                global_start=0,
                global_end=4,
                block_start=0,
                block_end=4,
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
        parser_name="legacy",
        parser_version="1",
        stats=VerificationStatistics(
            char_count=4,
            char_count_no_space=4,
            line_count=1,
            paragraph_count=1,
            language="zh",
            primary_count=4,
            primary_label="总字数",
        ),
        issues=(
            Issue(
                issue_id=issue_id,
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
                alternatives=["账户"],
                type="typo",
                severity=IssueSeverity.WARNING,
                layer="character",
                message="疑似错别字",
                description="疑似错别字",
                rule_id="cn_typo",
                rule_version="1",
                source="legacy",
                source_version="1",
                confidence=0.8,
                auto_fixable=True,
                context="帐号测试",
            ),
        ),
        summary=VerificationSummary(
            total=1,
            by_type={"typo": 1},
            by_severity={"warning": 1},
            by_rule={"cn_typo": 1},
            by_layer={"character": 1},
        ),
        execution_mode=VerificationExecutionMode.ASYNCHRONOUS,
        analysis_mode=VerificationAnalysisMode.LOCAL_ONLY,
        degradation=VerificationDegradation(),
    )
    VerificationRepository(session).save_result(job_id, result)
