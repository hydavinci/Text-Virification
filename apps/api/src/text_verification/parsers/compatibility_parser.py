from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from zipfile import BadZipFile

from docx.opc.exceptions import OpcError
from pdfminer.pdfexceptions import PDFException
from pydantic import ValidationError

from text_verification.compatibility.adapters import (
    parsed_file_to_document_model,
    source_version_for_file,
)
from text_verification.compatibility.parser import parse_file
from text_verification.domain.documents import DocumentModel, FileType
from text_verification.parsers.errors import ParserError

_EMPTY_FILE_ERROR = "File content is empty or no text could be extracted."
_GENERIC_PARSE_ERROR = "The compatibility parser could not parse the source."
_LEGACY_DETAIL_EXCEPTIONS = (ValueError,)
_LEGACY_PREFIXED_EXCEPTIONS = (BadZipFile, OpcError, PDFException, ValidationError)


@dataclass(frozen=True)
class CompatibilityParser:
    supported_type: FileType

    def parse(self, source_path: Path) -> DocumentModel:
        source_version = source_version_for_file(source_path)
        try:
            text, parsed_format, page_map = parse_file(
                str(source_path),
                self.supported_type.value,
                str(source_path.parent),
            )
            if not text.strip():
                raise ParserError(
                    _EMPTY_FILE_ERROR,
                    compatibility_detail=_EMPTY_FILE_ERROR,
                    compatibility_detail_format="direct",
                )
            return parsed_file_to_document_model(
                text=text,
                source_version=source_version,
                source_name=source_path.name,
                file_type=self.supported_type,
                parser_name=f"compatibility-{parsed_format}",
                page_map=page_map,
            )
        except _LEGACY_DETAIL_EXCEPTIONS as error:
            raise ParserError(
                _GENERIC_PARSE_ERROR,
                compatibility_detail=str(error),
                compatibility_detail_format="direct",
            ) from error
        except _LEGACY_PREFIXED_EXCEPTIONS as error:
            raise ParserError(
                _GENERIC_PARSE_ERROR,
                compatibility_detail=str(error),
                compatibility_detail_format="prefixed",
            ) from error
