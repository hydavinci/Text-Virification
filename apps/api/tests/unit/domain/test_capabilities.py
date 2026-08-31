from text_verification.domain.capabilities import (
    CapabilityProfile,
    default_capability_manifest,
)
from text_verification.domain.documents import FileType


def test_default_manifest_declares_seven_formats() -> None:
    manifest = default_capability_manifest()

    assert [item.file_type for item in manifest.formats] == [
        FileType.DOCX,
        FileType.DOC,
        FileType.PDF,
        FileType.TXT,
        FileType.RTF,
        FileType.MARKDOWN,
        FileType.CSV,
    ]
    assert manifest.for_type(FileType.PDF).supports_ocr is True


def test_manifest_declares_distinct_sync_and_async_format_profiles() -> None:
    manifest = default_capability_manifest()

    assert manifest.file_types_for_profile(CapabilityProfile.SYNCHRONOUS_COMPATIBILITY) == (
        FileType.DOCX,
        FileType.DOC,
        FileType.PDF,
        FileType.TXT,
        FileType.RTF,
        FileType.MARKDOWN,
        FileType.CSV,
    )
    assert manifest.file_types_for_profile(CapabilityProfile.ASYNCHRONOUS_JOB) == (
        FileType.DOCX,
        FileType.PDF,
        FileType.TXT,
    )


def test_manifest_produces_api_format_and_mime_declarations() -> None:
    manifest = default_capability_manifest()

    assert manifest.api_formats(CapabilityProfile.SYNCHRONOUS_COMPATIBILITY) == [
        {"ext": "docx", "name": "Word 文档", "accept": ".docx"},
        {"ext": "doc", "name": "旧版 Word 文档", "accept": ".doc"},
        {"ext": "pdf", "name": "PDF 文档", "accept": ".pdf"},
        {"ext": "txt", "name": "纯文本文件", "accept": ".txt"},
        {"ext": "rtf", "name": "RTF 文档", "accept": ".rtf"},
        {"ext": "md", "name": "Markdown 文件", "accept": ".md"},
        {"ext": "csv", "name": "CSV 文件", "accept": ".csv"},
    ]
    assert manifest.for_type(FileType.DOCX).mime_types == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
