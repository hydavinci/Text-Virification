from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, String
from sqlalchemy.dialects.postgresql import JSONB

from text_verification.infrastructure.orm import ReviewRevisionRow

BACKEND_ROOT = Path(__file__).resolve().parents[3]
PROVENANCE_MIGRATION_PATH = (
    BACKEND_ROOT
    / "alembic/versions/0012_add_review_revision_verified_provenance.py"
)


def test_review_revision_schema_persists_parent_and_kind_identity() -> None:
    columns = ReviewRevisionRow.__table__.columns
    assert columns["parent_revision_id"].nullable is True
    assert columns["kind"].nullable is False
    assert any(
        isinstance(constraint, ForeignKeyConstraint)
        and tuple(column.name for column in constraint.columns)
        == ("parent_revision_id", "verification_run_id")
        and tuple(element.target_fullname for element in constraint.elements)
        == (
            "review_revisions.review_revision_id",
            "review_revisions.verification_run_id",
        )
        for constraint in ReviewRevisionRow.__table__.constraints
    )


def test_review_revision_schema_persists_verified_provenance_jsonb() -> None:
    columns = ReviewRevisionRow.__table__.columns

    assert "verified_provenance" in columns
    assert columns["verified_provenance"].nullable is True
    assert isinstance(columns["verified_provenance"].type, JSONB)
    assert "provenance_state" in columns
    assert columns["provenance_state"].nullable is False
    assert isinstance(columns["provenance_state"].type, String)
    assert any(
        isinstance(constraint, CheckConstraint)
        and constraint.name == "ck_review_revisions_provenance_state"
        for constraint in ReviewRevisionRow.__table__.constraints
    )


def test_review_revision_provenance_migration_has_upgrade_and_downgrade() -> None:
    assert PROVENANCE_MIGRATION_PATH.is_file()
    spec = spec_from_file_location(
        "review_revision_provenance_migration",
        PROVENANCE_MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert migration.revision == "0012_add_revision_provenance"
    assert migration.down_revision == "0011_add_artifact_reservation_version"
    assert callable(migration.upgrade)
    assert callable(migration.downgrade)
    provenance = migration._derive_original_result_provenance(
        job_id="10000000-0000-4000-8000-000000000001",
        document_id="20000000-0000-4000-8000-000000000002",
        verification_run_id="30000000-0000-4000-8000-000000000003",
        source_version="sha256:source",
        source_text="帐号测试",
        revision_kind="review",
        revision_text="账号测试",
        issues=[
            {
                "start": 0,
                "end": 2,
                "suggestion": "账号",
                "alternatives": ["账户"],
            }
        ],
    )
    assert provenance == {
        "kind": "original_result",
        "job_id": "10000000-0000-4000-8000-000000000001",
        "base_result": {
            "document_id": "20000000-0000-4000-8000-000000000002",
            "verification_run_id": "30000000-0000-4000-8000-000000000003",
            "source_version": "sha256:source",
            "text_sha256": migration._text_sha256("帐号测试"),
        },
        "revision_text_sha256": migration._text_sha256("账号测试"),
    }
    assert migration._derive_original_result_provenance(
        job_id="10000000-0000-4000-8000-000000000001",
        document_id="20000000-0000-4000-8000-000000000002",
        verification_run_id="30000000-0000-4000-8000-000000000003",
        source_version="sha256:source",
        source_text="帐号测试",
        revision_kind="manual",
        revision_text="任意手工文本",
        issues=[],
    ) is None
    assert any(
        isinstance(constraint, CheckConstraint)
        and constraint.name == "ck_review_revisions_kind"
        for constraint in ReviewRevisionRow.__table__.constraints
    )
