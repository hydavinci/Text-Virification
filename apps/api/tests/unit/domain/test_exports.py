from importlib import import_module
from pathlib import PurePosixPath
from uuid import uuid4

import pytest


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


def _export_symbols():
    try:
        module = import_module("text_verification.domain.exports")
    except ModuleNotFoundError as error:
        pytest.fail(f"Export naming is not implemented yet: {error}")

    try:
        return module.ExportType, module.build_export_artifact
    except AttributeError as error:
        pytest.fail(f"Export naming is not implemented yet: {error}")
