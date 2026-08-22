from importlib import import_module
from pathlib import PurePosixPath
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from text_verification.domain.exports import (
    ExportSnapshot,
    deserialize_export_snapshot,
    serialize_export_snapshot,
)


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
