from text_verification.compatibility.analyzer import Issue
from text_verification.domain.documents import DocumentModel, FileType
from text_verification.domain.issues import (
    MAX_VERIFICATION_ISSUES,
    IssueLimitExceededError,
    validate_issue_count,
)
from text_verification.domain.ports import CheckContext
from text_verification.scenarios.models import RuleInput
from text_verification.scenarios.registry import get_profile


def _has_complete_structure(document: DocumentModel) -> bool:
    return document.file_type in {FileType.TXT, FileType.MARKDOWN}


def skipped_scenario_reasons(document: DocumentModel, context: CheckContext) -> tuple[str, ...]:
    if _has_complete_structure(document):
        return ()
    return tuple(
        f"scenario_rule_skipped:{rule.rule_id}:{rule.name}"
        for rule in get_profile(context.scenario.value).rules
        if rule.requires_complete_structure
    )


def check_scenario(
    document: DocumentModel,
    context: CheckContext,
    *,
    max_issues: int = MAX_VERIFICATION_ISSUES,
) -> list[Issue]:
    validate_issue_count((), max_issues=max_issues)
    profile = get_profile(context.scenario.value)
    if not profile.rules or not document.text.strip():
        return []
    source = RuleInput(
        text=document.text,
        complete_structure=_has_complete_structure(document),
        glossary_terms=frozenset(
            item["standard"].strip() for item in context.custom_glossary
            if item.get("standard", "").strip()
        ),
    )
    issues: list[Issue] = []
    seen: set[tuple[str, int, int]] = set()
    for rule in profile.rules:
        if rule.requires_complete_structure and not source.complete_structure:
            continue
        for finding in rule.check(source):
            if not 0 <= finding.start < finding.end <= len(source.text):
                raise ValueError(f"Invalid source span from scenario rule {rule.rule_id}")
            if not rule.allow_technical and not source.is_prose(finding.start, finding.end):
                continue
            key = rule.rule_id, finding.start, finding.end
            if key in seen:
                continue
            if len(issues) >= max_issues:
                raise IssueLimitExceededError("Scenario rules exceeded the remaining issue budget.")
            seen.add(key)
            issues.append(Issue(
                type=finding.type,
                severity=finding.severity,
                original=source.text[finding.start:finding.end],
                suggestion=None,
                position=finding.start,
                end_position=finding.end,
                context=source.text[max(0, finding.start - 40):finding.end + 40],
                description=finding.description,
                rule_id=rule.rule_id,
                layer="discourse",
                confidence=finding.confidence,
            ))
    return sorted(issues, key=lambda issue: (issue.position, issue.end_position, issue.rule_id))
