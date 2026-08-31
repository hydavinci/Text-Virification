from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from text_verification.compatibility.adapters import (
    parsed_file_to_document_model,
    source_version_for_file,
)
from text_verification.compatibility.parser import parse_file
from text_verification.domain.documents import DocumentModel, FileType

_EMPTY_FILE_ERROR = "File content is empty or no text could be extracted."


@dataclass(frozen=True)
class CompatibilityParser:
    supported_type: FileType

    def parse(self, source_path: Path) -> DocumentModel:
        source_version = source_version_for_file(source_path)
        text, parsed_format, page_map = parse_file(
            str(source_path),
            self.supported_type.value,
            str(source_path.parent),
        )
        if not text.strip():
            raise ValueError(_EMPTY_FILE_ERROR)
        return parsed_file_to_document_model(
            text=text,
            source_version=source_version,
            source_name=source_path.name,
            file_type=self.supported_type,
            parser_name=f"compatibility-{parsed_format}",
            page_map=page_map,
        )
