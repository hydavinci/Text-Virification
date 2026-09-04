from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

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
