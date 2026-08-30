from text_verification.domain.capabilities import default_capability_manifest
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
