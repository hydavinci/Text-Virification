from datetime import UTC, datetime
from importlib import import_module
from pathlib import PurePosixPath
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from text_verification.checkers.models import CheckCategory
from text_verification.domain.documents import DocumentModel, FileType
from text_verification.domain.exports import (
    ExportIssueSummarySnapshot,
    ExportSnapshot,
    deserialize_export_snapshot,
    serialize_export_snapshot,
)
from text_verification.domain.issues import (
    DecisionAction,
    Issue,
    IssueDecisionSummary,
    IssueSeverity,
)
from text_verification.workers.export_tasks import _plan_from_snapshot


@pytest.mark.parametrize(
    ("export_type_name", "extension", "expected_file_name"),
    [
        ("MODIFIED_DOCUMENT", "txt", "modified_document.txt"),
        ("MODIFIED_DOCUMENT", "docx", "modified_document.docx"),
        ("HTML_REPORT", "html", "report.html"),
        ("PDF_REPORT", "pdf", "report.pdf"),
    ],
    ids=["modified-txt", "modified-docx", "html-report", "pdf-report"],
)
def test_build_export_artifact_uses_server_generated_names(
    export_type_name: str,
    extension: str,
    expected_file_name: str,
) -> None:
    ExportType, build_export_artifact = _export_symbols()
    job_id = uuid4()
    export_id = uuid4()
    export_type = getattr(ExportType, export_type_name)

    artifact = build_export_artifact(
        job_id=job_id,
        export_id=export_id,
        export_type=export_type,
        extension=extension,
    )

    assert artifact.file_name == expected_file_name
    assert artifact.storage_name == f"{export_id}.{extension}"
    assert artifact.storage_key == str(PurePosixPath(str(job_id)) / artifact.storage_name)


@pytest.mark.parametrize(
    ("export_type_name", "extension"),
    [
        ("MODIFIED_DOCUMENT", "html"),
        ("MODIFIED_DOCUMENT", "pdf"),
        ("HTML_REPORT", "pdf"),
        ("PDF_REPORT", "html"),
    ],
    ids=[
        "modified-with-html",
        "modified-with-pdf",
        "html-report-with-pdf",
        "pdf-report-with-html",
    ],
)
def test_build_export_artifact_rejects_mismatched_type_and_extension(
    export_type_name: str,
    extension: str,
) -> None:
    ExportType, build_export_artifact = _export_symbols()
    export_type = getattr(ExportType, export_type_name)

    with pytest.raises(ValueError, match="supports extension"):
        build_export_artifact(
            job_id=uuid4(),
            export_id=uuid4(),
            export_type=export_type,
            extension=extension,
        )


def test_export_snapshot_v2_requires_version_and_decision_hash() -> None:
    payload = _snapshot_payload(schema_version=2)

    with pytest.raises(ValidationError):
        ExportSnapshot.model_validate(payload)


def test_export_snapshot_v2_serializes_version_and_decision_hash() -> None:
    version_id = UUID("00000000-0000-0000-0000-000000000100")
    snapshot = ExportSnapshot.model_validate(
        {
            **_snapshot_payload(schema_version=2),
            "document_version_id": str(version_id),
            "decision_snapshot_sha256": "a" * 64,
        }
    )

    serialized = serialize_export_snapshot(snapshot)

    assert serialized["schema_version"] == 2
    assert serialized["document_version_id"] == str(version_id)
    assert serialized["decision_snapshot_sha256"] == "a" * 64


def test_deserialize_export_snapshot_accepts_queued_schema_v1_payload() -> None:
    snapshot = deserialize_export_snapshot(_snapshot_payload(schema_version=1))

    assert snapshot is not None
    assert snapshot.schema_version == 1
    assert snapshot.document_version_id is None
    assert snapshot.decision_snapshot_sha256 is None


def test_schema_v1_export_snapshot_uses_legacy_warning_plan() -> None:
    document_id = uuid4()
    document = DocumentModel.model_validate(
        {
            "document_id": str(document_id),
            "file_type": "txt",
            "source_name": "analysis.txt",
            "version": 1,
            "blocks": [
                {
                    "block_id": "p-000001",
                    "kind": "paragraph",
                    "text": "正文",
                    "page": None,
                    "paragraph_index": 0,
                    "parent_id": None,
                    "style": {},
                    "source_locator": {"paragraph_index": 0},
                }
            ],
            "metadata": {"encoding": "utf-8"},
        }
    )
    issue = Issue(
        issue_id=uuid4(),
        document_id=document_id,
        block_id="p-000001",
        page=None,
        start=0,
        end=2,
        original="错文",
        suggestion="替换",
        alternatives=["替换"],
        type="literal",
        severity=IssueSeverity.WARNING,
        layer=CheckCategory.CHARACTER.value,
        message="命中规则。",
        rule_id="character-001",
        source="test",
        source_version="1",
        confidence=1.0,
        auto_fixable=True,
        context="错文",
        decision=IssueDecisionSummary(
            issue_version=1,
            revision=0,
            action=DecisionAction.ACCEPTED,
            replacement="替换",
            suggestion_id=None,
            updated_at=datetime.now(UTC),
        ),
    )
    snapshot = ExportSnapshot(
        schema_version=1,
        captured_at=datetime.now(UTC),
        source_name="analysis.txt",
        source_type=FileType.TXT,
        source_size_bytes=6,
        source_sha256=None,
        scenario="general",
        enabled_categories=[CheckCategory.CHARACTER],
        completed_categories=[CheckCategory.CHARACTER],
        checker_failures=[],
        summary=ExportIssueSummarySnapshot(
            total=1,
            by_category={CheckCategory.CHARACTER: 1},
            by_severity={IssueSeverity.WARNING: 1},
            by_decision={"accepted": 1},
        ),
        document=document,
        issues=[issue],
        preflight_warnings=[],
    )

    plan = _plan_from_snapshot(snapshot)

    assert plan.applicable == []
    assert [(warning.code, warning.issue_id) for warning in plan.warnings] == [
        ("original_text_mismatch", issue.issue_id)
    ]


def test_deserialize_schema_v1_maps_legacy_custom_decisions_without_fallback() -> None:
    issue_id = uuid4()
    payload = _snapshot_payload(schema_version=1)
    payload["document"] = _document_payload(text="正文")
    payload["issues"] = [
        _issue_payload(
            issue_id=issue_id,
            original="正文",
            suggestion="不要回退到建议",
            decision={
                "issue_version": 1,
                "revision": 0,
                "action": "custom",
                "replacement": None,
                "suggestion_id": None,
                "updated_at": "2026-08-22T04:00:00Z",
            },
        )
    ]

    snapshot = deserialize_export_snapshot(payload)
    assert snapshot is not None

    plan = _plan_from_snapshot(snapshot)

    assert plan.applicable == []
    assert [(warning.code, warning.issue_id) for warning in plan.warnings] == [
        ("missing_replacement_value", issue_id)
    ]


def test_schema_v1_snapshot_with_optional_v2_metadata_still_uses_legacy_plan() -> None:
    issue_id = uuid4()
    payload = {
        **_snapshot_payload(schema_version=1),
        "document": _document_payload(text="正文"),
        "document_version_id": str(uuid4()),
        "decision_snapshot_sha256": "a" * 64,
        "issues": [
            _issue_payload(
                issue_id=issue_id,
                original="错文",
                suggestion="替换",
                decision={
                    "issue_version": 1,
                    "revision": 0,
                    "action": "accepted",
                    "replacement": "替换",
                    "suggestion_id": None,
                    "updated_at": "2026-08-22T04:00:00Z",
                },
            )
        ],
    }
    snapshot = deserialize_export_snapshot(payload)
    assert snapshot is not None

    plan = _plan_from_snapshot(snapshot)

    assert plan.applicable == []
    assert [(warning.code, warning.issue_id) for warning in plan.warnings] == [
        ("original_text_mismatch", issue_id)
    ]


def _export_symbols():
    try:
        module = import_module("text_verification.domain.exports")
    except ModuleNotFoundError as error:
        pytest.fail(f"Export naming is not implemented yet: {error}")

    try:
        return module.ExportType, module.build_export_artifact
    except AttributeError as error:
        pytest.fail(f"Export naming is not implemented yet: {error}")


def _snapshot_payload(*, schema_version: int) -> dict[str, object]:
    return {
        "schema_version": schema_version,
        "captured_at": "2026-08-22T04:00:00Z",
        "source_name": "analysis.txt",
        "source_type": "txt",
        "source_size_bytes": 4,
        "source_sha256": None,
        "scenario": "general",
        "enabled_categories": [],
        "completed_categories": [],
        "checker_failures": [],
        "summary": {
            "total": 0,
            "by_category": {},
            "by_severity": {},
            "by_decision": {},
        },
        "document": {
            "document_id": "00000000-0000-0000-0000-000000000001",
            "file_type": "txt",
            "source_name": "analysis.txt",
            "version": 1,
            "blocks": [],
            "metadata": {},
        },
        "issues": [],
        "preflight_warnings": [],
    }


def _document_payload(*, text: str) -> dict[str, object]:
    return {
        "document_id": "00000000-0000-0000-0000-000000000001",
        "file_type": "txt",
        "source_name": "analysis.txt",
        "version": 1,
        "blocks": [
            {
                "block_id": "p-000001",
                "kind": "paragraph",
                "text": text,
                "page": None,
                "paragraph_index": 0,
                "parent_id": None,
                "style": {},
                "source_locator": {"paragraph_index": 0},
            }
        ],
        "metadata": {},
    }


def _issue_payload(
    *,
    issue_id: UUID,
    original: str,
    suggestion: str | None,
    decision: dict[str, object],
) -> dict[str, object]:
    return {
        "issue_id": str(issue_id),
        "document_id": "00000000-0000-0000-0000-000000000001",
        "document_version": 1,
        "block_id": "p-000001",
        "page": None,
        "start": 0,
        "end": 2,
        "original": original,
        "suggestion": suggestion,
        "alternatives": [] if suggestion is None else [suggestion],
        "suggestions": [],
        "type": "literal",
        "severity": "warning",
        "layer": "character",
        "message": "命中规则。",
        "rule_id": "character-001",
        "source": "test",
        "source_version": "1",
        "confidence": 1.0,
        "auto_fixable": suggestion is not None,
        "context": original,
        "decision": decision,
    }
