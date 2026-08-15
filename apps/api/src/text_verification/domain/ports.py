from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

from text_verification.domain.documents import DocumentModel, FileType
from text_verification.domain.issues import Issue


@dataclass(frozen=True)
class CheckContext:
    industry_dictionary_ids: tuple[str, ...]
    personal_dictionary: tuple[dict[str, str], ...]


class Parser(Protocol):
    supported_type: FileType

    def parse(
        self,
        source_path: Path,
        *,
        document_id: UUID,
        source_name: str,
    ) -> DocumentModel: ...


class Checker(Protocol):
    name: str
    version: str
    supported_languages: set[str]

    def check(self, document: DocumentModel, context: CheckContext) -> list[Issue]: ...


class Exporter(Protocol):
    file_type: FileType

    def export(self, document: DocumentModel, issues: list[Issue], target: Path) -> Path: ...
