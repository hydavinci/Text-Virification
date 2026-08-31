import hashlib
from uuid import NAMESPACE_URL, uuid4, uuid5

from text_verification.compatibility.adapters import (
    legacy_issue_to_domain,
    parsed_file_to_document_model,
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


def test_uploaded_docx_page_map_becomes_structured_paragraph_blocks() -> None:
    document = parsed_file_to_document_model(
        text="Alpha\nBeta",
        source_name="source.docx",
        file_type=FileType.DOCX,
        parser_name="compatibility-docx",
        page_map=[
            (0, 5, "第1段"),
            (6, 10, "第2段"),
        ],
    )

    assert [block.text for block in document.blocks] == ["Alpha", "Beta"]
    assert [block.global_start for block in document.blocks] == [0, 6]
    assert [block.global_end for block in document.blocks] == [5, 10]
    assert [block.block_start for block in document.blocks] == [0, 0]
    assert [block.block_end for block in document.blocks] == [5, 4]
    assert [block.page for block in document.blocks] == [None, None]
    assert [block.paragraph_index for block in document.blocks] == [0, 1]
    assert document.blocks[0].source_locator == {
        "label": "第1段",
        "paragraph_index": 0,
        "paragraph_number": 1,
        "locator_kind": "paragraph",
    }
    assert document.blocks[1].source_locator == {
        "label": "第2段",
        "paragraph_index": 1,
        "paragraph_number": 2,
        "locator_kind": "paragraph",
    }


def test_uploaded_issue_maps_to_containing_block_and_local_offsets() -> None:
    document = parsed_file_to_document_model(
        text="Clean\n帐号",
        source_name="source.pdf",
        file_type=FileType.PDF,
        parser_name="compatibility-pdf",
        page_map=[
            (0, 5, "第1页"),
            (6, 8, "第2页"),
        ],
    )
    legacy_issue = LegacyIssue(
        type="typo",
        severity="warning",
        original="帐号",
        suggestion="账号",
        position=6,
        end_position=8,
        context="Clean\n帐号",
        description="疑似错别字",
        rule_id="cn_typo",
        alternatives=["账号"],
        layer="character",
    )

    adapted = legacy_issue_to_domain(legacy_issue, document, uuid4())

    assert adapted.block_id == document.blocks[1].block_id
    assert adapted.page == 2
    assert adapted.block_start == 0
    assert adapted.block_end == 2
    assert document.blocks[1].text[adapted.block_start : adapted.block_end] == adapted.original
    assert document.blocks[1].source_locator == {
        "label": "第2页",
        "page": 2,
        "locator_kind": "page",
    }


def test_uploaded_without_location_map_uses_file_level_block_without_page_numbers() -> None:
    document = parsed_file_to_document_model(
        text="No structure here",
        source_name="source.rtf",
        file_type=FileType.RTF,
        parser_name="compatibility-rtf",
        page_map=[],
    )

    assert len(document.blocks) == 1
    assert document.blocks[0].block_id == "file-0"
    assert document.blocks[0].page is None
    assert document.blocks[0].paragraph_index is None
    assert document.blocks[0].source_locator == {
        "locator_kind": "file",
        "note": "parser returned no structural location map",
    }


def test_legacy_response_keeps_existing_fields_and_adds_canonical_metadata() -> None:
    result = _result()

    payload = verification_result_to_legacy_response(result)

    assert EXISTING_TOP_LEVEL_FIELDS <= set(payload)
    assert payload["document_id"] == str(result.document_id)
    assert payload["verification_run_id"] == str(result.verification_run_id)
    expected_source_version = (
        f"sha256:{hashlib.sha256(result.text.encode('utf-8')).hexdigest()}"
    )
    assert payload["source_version"] == expected_source_version
    assert payload["execution_mode"] == result.execution_mode.value
    assert payload["dictionary_versions"] == result.dictionary_versions
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
        dictionary_versions={
            "sensitive_rules": "sha256-sensitive",
            "ad_extreme_words": "sha256-ad-extreme",
        },
        degradation=VerificationDegradation(
            is_degraded=True,
            reasons=("llm_review_disabled",),
        ),
    )
