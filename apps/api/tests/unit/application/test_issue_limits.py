from __future__ import annotations

import sys
from dataclasses import dataclass, field
from types import FrameType, SimpleNamespace
from uuid import uuid4

import pytest

from text_verification.checkers.registry import CheckerRegistry
from text_verification.compatibility.analyzer import TextAnalyzer
from text_verification.domain import issues as issue_domain
from text_verification.domain.documents import DocumentModel, FileType, TextBlock
from text_verification.domain.issues import Issue, IssueSeverity
from text_verification.domain.ports import CheckContext

MAX_VERIFICATION_ISSUES = getattr(
    issue_domain,
    "MAX_VERIFICATION_ISSUES",
    100_000,
)
IssueLimitExceededError = getattr(
    issue_domain,
    "IssueLimitExceededError",
    ValueError,
)


class CountingIssues:
    def __init__(self, issues: list[Issue]) -> None:
        self._issues = issues
        self.reads = 0

    def __iter__(self):
        for issue in self._issues:
            self.reads += 1
            yield issue


@dataclass
class RecordingChecker:
    issues: CountingIssues
    name: str = "recording"
    version: str = "1"
    supported_languages: set[str] = field(default_factory=lambda: {"zh"})

    def check(self, document, context, *, progress_observer=None):
        del document, context, progress_observer
        return SimpleNamespace(issues=self.issues, dictionary_versions={})


def test_checker_aggregation_accepts_exact_limit_and_stops_at_one_over() -> None:
    document = _document()
    run_id = uuid4()
    exact = CountingIssues([_issue(document, run_id), _issue(document, run_id)])

    result = CheckerRegistry(
        [RecordingChecker(exact)],
        max_issues=2,
    ).run(document, CheckContext(verification_run_id=run_id))

    assert len(result.issues) == 2
    assert exact.reads == 2

    over = CountingIssues(
        [_issue(document, run_id), _issue(document, run_id), _issue(document, run_id)]
    )
    with pytest.raises(IssueLimitExceededError):
        CheckerRegistry(
            [RecordingChecker(over)],
            max_issues=2,
        ).run(document, CheckContext(verification_run_id=run_id))
    assert over.reads == 3


def test_legacy_repeated_typo_production_stops_at_limit_plus_one() -> None:
    analyzer = TextAnalyzer(max_issues=2)

    with pytest.raises(IssueLimitExceededError):
        analyzer.analyze(
            "帐号帐号帐号" + "正常文本" * 10_000,
            enable_security=False,
            enable_sensitive=False,
        )


@pytest.mark.parametrize(
    "text",
    [
        "(" * 10_000,
        "「" * 10_000,
    ],
    ids=["brackets", "quotes"],
)
def test_bracket_quote_staging_never_exceeds_remaining_issue_budget(
    text: str,
) -> None:
    analyzer = TextAnalyzer(max_issues=2)
    max_lengths: dict[str, int] = {}
    previous_trace = sys.gettrace()

    def trace(frame: FrameType, event: str, arg):
        del arg
        if event == "call":
            if frame.f_code.co_name in {"_check_brackets_quotes", "check_scope"}:
                return trace
            return None
        if frame.f_code.co_name not in {"_check_brackets_quotes", "check_scope"}:
            return trace
        if event in {"line", "return"}:
            for name, value in frame.f_locals.items():
                if not hasattr(value, "append") or not hasattr(value, "pop"):
                    continue
                try:
                    current_length = len(value)
                except TypeError:
                    continue
                max_lengths[name] = max(max_lengths.get(name, 0), current_length)
        return trace

    try:
        sys.settrace(trace)
        with pytest.raises(IssueLimitExceededError):
            analyzer.analyze(
                text,
                enable_security=False,
                enable_sensitive=False,
            )
    finally:
        sys.settrace(previous_trace)

    assert max_lengths
    assert all(length <= 2 for length in max_lengths.values())


def test_canonical_issue_count_helper_accepts_exact_limit_and_rejects_one_over() -> None:
    validate_issue_count = getattr(
        issue_domain,
        "validate_issue_count",
        lambda _values: None,
    )
    validate_issue_count(range(MAX_VERIFICATION_ISSUES))

    with pytest.raises(IssueLimitExceededError):
        validate_issue_count(range(MAX_VERIFICATION_ISSUES + 1))


def _document() -> DocumentModel:
    text = "帐号"
    return DocumentModel(
        document_id=uuid4(),
        source_version="sha256:sample",
        file_type=FileType.TXT,
        source_name="sample.txt",
        text=text,
        blocks=[
            TextBlock(
                block_id="p-0",
                kind="paragraph",
                text=text,
                global_start=0,
                global_end=2,
                block_start=0,
                block_end=2,
                page=None,
                paragraph_index=0,
                table_index=None,
                row_index=None,
                cell_index=None,
                bbox=None,
                parent_id=None,
                style={},
                source_locator={"paragraph_index": 0},
            )
        ],
        parser_name="test",
        parser_version="1",
    )


def _issue(document: DocumentModel, run_id) -> Issue:
    return Issue(
        issue_id=uuid4(),
        document_id=document.document_id,
        verification_run_id=run_id,
        block_id="p-0",
        page=None,
        start=0,
        end=2,
        block_start=0,
        block_end=2,
        original="帐号",
        suggestion="账号",
        alternatives=[],
        type="typo",
        severity=IssueSeverity.WARNING,
        layer="character",
        message="疑似错别字",
        description="疑似错别字",
        rule_id="cn_typo",
        rule_version="1",
        source="test",
        source_version="1",
        confidence=0.8,
        auto_fixable=True,
        context="帐号",
    )
