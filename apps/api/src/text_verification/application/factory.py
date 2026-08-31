from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from text_verification.application.errors import ReviewerError
from text_verification.application.verification_pipeline import (
    ReviewMetadata,
    VerificationPipeline,
)
from text_verification.checkers.compatibility_checker import CompatibilityChecker
from text_verification.checkers.registry import CheckerRegistry
from text_verification.compatibility.analyzer import Issue as LegacyIssue
from text_verification.compatibility.llm_review import (
    is_llm_review_configured,
    review_issues,
)
from text_verification.config import Settings, get_settings
from text_verification.domain.documents import DocumentModel, FileType
from text_verification.domain.issues import Issue, IssueSeverity
from text_verification.domain.ports import Parser
from text_verification.parsers.compatibility_parser import CompatibilityParser
from text_verification.parsers.registry import ParserRegistry


@dataclass(frozen=True)
class CompatibilityIssueReviewer:
    settings: Settings

    def review(
        self,
        document: DocumentModel,
        issues: tuple[Issue, ...],
    ) -> tuple[tuple[Issue, ...], ReviewMetadata | None]:
        if not is_llm_review_configured(self.settings):
            return issues, None

        legacy_issues = [_to_legacy_issue(issue) for issue in issues]
        source_by_legacy_id = {
            id(legacy_issue): issue
            for legacy_issue, issue in zip(legacy_issues, issues, strict=True)
        }
        reviewed, metadata = review_issues(self.settings, document.text, legacy_issues)
        if metadata.get("failed"):
            failure_code = str(metadata.get("failure_code") or "llm_review_failed")
            retryable = metadata.get("retryable")
            if not isinstance(retryable, bool):
                retryable = failure_code in {"llm_provider_error", "llm_timeout"}
            raise ReviewerError(
                code=failure_code,
                message=str(metadata.get("reason") or "LLM review failed."),
                retryable=retryable,
                metadata=dict(metadata),
            )
        return (
            tuple(
                _apply_legacy_review(source_by_legacy_id[id(legacy_issue)], legacy_issue)
                for legacy_issue in reviewed
            ),
            dict(metadata),
        )


def build_default_verification_pipeline(
    settings: Settings | None = None,
) -> VerificationPipeline:
    resolved_settings = settings or get_settings()
    return VerificationPipeline(
        parsers=ParserRegistry(
            cast(Parser, CompatibilityParser(file_type)) for file_type in FileType
        ),
        checkers=CheckerRegistry([CompatibilityChecker()]),
        reviewer=CompatibilityIssueReviewer(resolved_settings),
    )


def _to_legacy_issue(issue: Issue) -> LegacyIssue:
    return LegacyIssue(
        type=issue.type,
        severity=issue.severity.value,
        original=issue.original,
        suggestion=issue.suggestion,
        position=issue.start,
        end_position=issue.end,
        context=issue.context,
        description=issue.description,
        rule_id=issue.rule_id,
        alternatives=list(issue.alternatives),
        layer=issue.layer,
        review=issue.review or "",
        review_reason=issue.review_reason or "",
    )


def _apply_legacy_review(issue: Issue, reviewed: LegacyIssue) -> Issue:
    updates: dict[str, Any] = {
        "severity": IssueSeverity(reviewed.severity),
        "description": reviewed.description,
        "review": reviewed.review or None,
        "review_reason": reviewed.review_reason or None,
    }
    return issue.model_copy(update=updates)
