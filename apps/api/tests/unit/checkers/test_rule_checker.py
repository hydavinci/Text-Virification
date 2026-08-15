from uuid import UUID

from text_verification.checkers.models import CheckCategory, LiteralRule
from text_verification.checkers.rule_checker import RuleChecker
from text_verification.domain.documents import DocumentModel, FileType, TextBlock
from text_verification.domain.issues import IssueSeverity
from text_verification.domain.ports import CheckContext


def test_rule_checker_emits_unicode_code_point_offsets() -> None:
    document = build_document("A😀绝对领先B")
    checker = RuleChecker(build_rule("ad-001", CheckCategory.SECURITY, "绝对领先", "领先"))

    issues = checker.check(document, CheckContext((), ()))

    assert [(issue.start, issue.end, issue.original) for issue in issues] == [
        (2, 6, "绝对领先"),
    ]


def test_rule_checker_generates_deterministic_issue_ids() -> None:
    document = build_document("绝对领先，持续绝对领先")
    checker = RuleChecker(build_rule("ad-001", CheckCategory.SECURITY, "绝对领先", "领先"))

    first = checker.check(document, CheckContext((), ()))
    second = checker.check(document, CheckContext((), ()))

    assert [issue.issue_id for issue in first] == [issue.issue_id for issue in second]


def build_document(text: str) -> DocumentModel:
    return DocumentModel(
        document_id=UUID("00000000-0000-0000-0000-000000000001"),
        file_type=FileType.TXT,
        source_name="sample.txt",
        version=1,
        blocks=[
            TextBlock(
                block_id="p-000001",
                kind="paragraph",
                text=text,
                page=None,
                paragraph_index=0,
                parent_id=None,
                style={},
                source_locator={"paragraph_index": 0},
            )
        ],
        metadata={},
    )


def build_rule(
    rule_id: str,
    category: CheckCategory,
    pattern: str,
    suggestion: str,
) -> LiteralRule:
    return LiteralRule(
        id=rule_id,
        category=category,
        severity=IssueSeverity.WARNING,
        pattern=pattern,
        suggestion=suggestion,
        message="避免使用绝对化表述。",
        scenarios=frozenset(),
        auto_fixable=True,
    )
