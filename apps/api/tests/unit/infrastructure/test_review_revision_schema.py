from sqlalchemy import CheckConstraint, ForeignKeyConstraint

from text_verification.infrastructure.orm import ReviewRevisionRow


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
    assert any(
        isinstance(constraint, CheckConstraint)
        and constraint.name == "ck_review_revisions_kind"
        for constraint in ReviewRevisionRow.__table__.constraints
    )
