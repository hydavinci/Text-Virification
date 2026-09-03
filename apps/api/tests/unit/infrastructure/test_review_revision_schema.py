from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from sqlalchemy import CheckConstraint, ForeignKeyConstraint
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
    assert any(
        isinstance(constraint, CheckConstraint)
        and constraint.name == "ck_review_revisions_verified_provenance_object"
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
    assert any(
        isinstance(constraint, CheckConstraint)
        and constraint.name == "ck_review_revisions_kind"
        for constraint in ReviewRevisionRow.__table__.constraints
    )
