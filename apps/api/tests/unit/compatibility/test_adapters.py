import hashlib
from uuid import NAMESPACE_URL, uuid4, uuid5

from text_verification.compatibility.adapters import (
    legacy_issue_to_domain,
    verification_result_to_legacy_response,
)
from text_verification.compatibility.analyzer import Issue as LegacyIssue
from text_verification.compatibility.models import Scenario as CompatibilityScenario
from text_verification.domain.documents import DocumentModel, FileType, TextBlock
from text_verification.domain.issues import Issue, IssueSeverity
from text_verification.domain.verification import (
    Scenario,
    VerificationDegradation,
    VerificationExecutionMode,
    VerificationResult,
    VerificationStatistics,
    VerificationSummary,
)

EXISTING_TOP_LEVEL_FIELDS = {
    "success",
    "filename",
    "text",
    "stats",
    "issues",
    "summary",
    "file_id",
    "file_ext",
    "scenario",
}

EXISTING_ISSUE_FIELDS = {
    "type",
    "severity",
    "original",
    "suggestion",
    "position",
    "end_position",
    "context",
    "description",
    "rule_id",
    "alternatives",
    "layer",
    "review",
    "review_reason",
}


def test_compatibility_scenario_is_a_temporary_alias_of_the_canonical_domain_type() -> None:
    assert CompatibilityScenario is Scenario


def test_issue_adapter_builds_stable_issue_id() -> None:
    document = _document()
    legacy_issue = LegacyIssue(
        type="typo",
        severity="warning",
        original="帐号",
        suggestion="账号",
        position=0,
        end_position=2,
        context="帐号测试",
        description="疑似错别字",
        rule_id="cn_typo",
        alternatives=["账号"],
        layer="character",
    )
    run_id = uuid4()

    first = legacy_issue_to_domain(legacy_issue, document, run_id)
    second = legacy_issue_to_domain(legacy_issue, document, run_id)

    assert first.issue_id == uuid5(
        NAMESPACE_URL,
        (
            f"{document.source_version}:{legacy_issue.rule_id}:{legacy_issue.position}:"
            f"{legacy_issue.end_position}:{legacy_issue.original}"
        ),
    )
    assert first.issue_id == second.issue_id
    assert first.original == document.text[first.start:first.end]
    assert first.document_id == document.document_id
    assert first.verification_run_id == run_id


def test_issue_adapter_uses_original_width_when_legacy_range_is_empty() -> None:
    document = _document(text='""测试')
    legacy_issue = LegacyIssue(
        type="punctuation",
        severity="warning",
        original='""',
        suggestion='""',
        position=0,
        end_position=0,
        context="",
        description="引号数量不匹配",
        rule_id="unmatched_quote",
        alternatives=None,
        layer="format",
    )

    adapted = legacy_issue_to_domain(legacy_issue, document, uuid4())

    assert adapted.start == 0
    assert adapted.end == 2
    assert adapted.original == '""'


def test_legacy_response_keeps_existing_fields_and_adds_canonical_metadata() -> None:
    result = _result()

    payload = verification_result_to_legacy_response(result)

    assert EXISTING_TOP_LEVEL_FIELDS <= set(payload)
    assert payload["document_id"] == str(result.document_id)
    assert payload["verification_run_id"] == str(result.verification_run_id)
    assert payload["source_version"] == f"sha256:{hashlib.sha256(result.text.encode('utf-8')).hexdigest()}"
    assert payload["execution_mode"] == result.execution_mode.value
    assert payload["degradation"] == {
        "is_degraded": True,
        "reasons": ["llm_review_disabled"],
    }
    assert EXISTING_ISSUE_FIELDS <= set(payload["issues"][0])
    assert payload["issues"][0]["issue_id"] == str(result.issues[0].issue_id)
    assert payload["issues"][0]["position"] == result.issues[0].start
    assert payload["issues"][0]["end_position"] == result.issues[0].end


def _document(text: str = "帐号测试") -> DocumentModel:
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
                global_end=len(text),
                block_start=0,
                block_end=len(text),
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
        parser_name="compatibility-flat-text",
        parser_version="1",
    )


def _result() -> VerificationResult:
    document = _document()
    verification_run_id = uuid4()
    issue = Issue(
        issue_id=uuid4(),
        document_id=document.document_id,
        verification_run_id=verification_run_id,
        block_id=document.blocks[0].block_id,
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
        source="compatibility.analyzer",
        source_version="1",
        confidence=0.8,
        auto_fixable=True,
        context="帐号测试",
    )
    return VerificationResult(
        verification_run_id=verification_run_id,
        document_id=document.document_id,
        source_name=document.source_name,
        file_type=document.file_type,
        scenario=Scenario.BUSINESS,
        text=document.text,
        stats=VerificationStatistics(
            char_count=4,
            char_count_no_space=4,
            line_count=1,
            paragraph_count=1,
            language="zh",
            primary_count=4,
            primary_label="总字数",
        ),
        issues=(issue,),
        summary=VerificationSummary(
            total=1,
            by_type={"typo": 1},
            by_severity={"warning": 1},
            by_rule={"cn_typo": 1},
            by_layer={"character": 1},
        ),
        execution_mode=VerificationExecutionMode.RULES_WITH_OPTIONAL_LLM,
        degradation=VerificationDegradation(
            is_degraded=True,
            reasons=("llm_review_disabled",),
        ),
    )
