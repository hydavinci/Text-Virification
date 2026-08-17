import logging
from uuid import UUID, uuid4

from text_verification.checkers.models import (
    CheckCategory,
    CheckerFailure,
    CheckOptions,
    CheckScenario,
    LiteralRule,
)
from text_verification.checkers.registry import CheckerRegistry
from text_verification.checkers.rule_checker import RuleChecker
from text_verification.domain.documents import DocumentModel, FileType, TextBlock
from text_verification.domain.issues import Issue, IssueSeverity
from text_verification.domain.ports import CheckContext


def test_registry_keeps_successful_issues_when_one_category_fails() -> None:
    registry = CheckerRegistry(
        {
            CheckCategory.CHARACTER: StaticChecker([build_issue("character")]),
            CheckCategory.SECURITY: ExplodingChecker(RuntimeError("bad dictionary")),
        }
    )

    result = registry.run(
        build_document("正文"),
        CheckContext((), ()),
        CheckOptions(
            scenario=CheckScenario.GENERAL,
            enabled_categories=frozenset(
                {CheckCategory.CHARACTER, CheckCategory.SECURITY}
            ),
        ),
    )

    assert [issue.layer for issue in result.issues] == ["character"]
    assert result.completed_categories == {CheckCategory.CHARACTER}
    assert result.failures == {
        CheckCategory.SECURITY: CheckerFailure(
            code="checker_failed",
            message="安全检查暂时不可用。",
        )
    }


def test_registry_runs_only_enabled_categories() -> None:
    character_checker = StaticChecker([build_issue("character")])
    security_checker = StaticChecker([build_issue("security")])
    registry = CheckerRegistry(
        {
            CheckCategory.CHARACTER: character_checker,
            CheckCategory.SECURITY: security_checker,
        }
    )

    result = registry.run(
        build_document("正文"),
        CheckContext((), ()),
        CheckOptions(
            scenario=CheckScenario.GENERAL,
            enabled_categories=frozenset({CheckCategory.SECURITY}),
        ),
    )

    assert character_checker.calls == 0
    assert security_checker.calls == 1
    assert [issue.layer for issue in result.issues] == ["security"]
    assert result.completed_categories == {CheckCategory.SECURITY}


def test_registry_logs_only_category_and_exception_type(caplog) -> None:
    secret = "SECRET-DOC-CONTENT-8472"
    registry = CheckerRegistry(
        {
            CheckCategory.SECURITY: ExplodingChecker(
                RuntimeError(f"boom:{secret}:checker-message")
            )
        }
    )

    with caplog.at_level(logging.ERROR):
        result = registry.run(
            build_document("绝对领先的正文"),
            CheckContext((), ()),
            CheckOptions(
                scenario=CheckScenario.GENERAL,
                enabled_categories=frozenset({CheckCategory.SECURITY}),
            ),
        )

    assert result.issues == []
    assert result.completed_categories == set()
    assert result.failures == {
        CheckCategory.SECURITY: CheckerFailure(
            code="checker_failed",
            message="安全检查暂时不可用。",
        )
    }
    assert "RuntimeError" in caplog.text
    assert "绝对领先的正文" not in caplog.text
    assert secret not in caplog.text
    assert "checker-message" not in caplog.text


def test_registry_suppresses_rules_for_a_different_scenario() -> None:
    checker = RuleChecker(
        LiteralRule(
            id="legal-only-001",
            category=CheckCategory.SECURITY,
            severity=IssueSeverity.WARNING,
            pattern="绝对领先",
            suggestion="领先",
            message="避免使用绝对化表述。",
            scenarios=frozenset({CheckScenario.LEGAL}),
            auto_fixable=True,
        )
    )
    registry = CheckerRegistry({CheckCategory.SECURITY: checker})

    result = registry.run(
        build_document("绝对领先"),
        CheckContext((), ()),
        CheckOptions(
            scenario=CheckScenario.GENERAL,
            enabled_categories={CheckCategory.SECURITY},
        ),
    )

    assert result.issues == []
    assert result.completed_categories == {CheckCategory.SECURITY}
    assert result.failures == {}


class StaticChecker:
    name = "static"
    version = "1"
    supported_languages = {"zh-CN"}

    def __init__(self, issues: list[Issue]) -> None:
        self._issues = issues
        self.calls = 0

    def check(self, document: DocumentModel, context: CheckContext) -> list[Issue]:
        del document, context
        self.calls += 1
        return list(self._issues)


class ExplodingChecker:
    name = "explode"
    version = "1"
    supported_languages = {"zh-CN"}

    def __init__(self, error: Exception) -> None:
        self._error = error

    def check(self, document: DocumentModel, context: CheckContext) -> list[Issue]:
        del document, context
        raise self._error


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


def build_issue(layer: str) -> Issue:
    return Issue(
        issue_id=uuid4(),
        document_id=uuid4(),
        block_id="p-000001",
        page=None,
        start=0,
        end=2,
        original="正文",
        suggestion="正文",
        alternatives=[],
        type="literal",
        severity=IssueSeverity.WARNING,
        layer=layer,
        message="命中规则。",
        rule_id=f"{layer}-001",
        source="test",
        source_version="1",
        confidence=1,
        auto_fixable=True,
        context="正文",
    )
