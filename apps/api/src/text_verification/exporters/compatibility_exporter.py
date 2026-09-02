from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from text_verification.compatibility.exporters import ExportError, export_original
from text_verification.domain.documents import DocumentModel, FileType
from text_verification.domain.issues import Issue
from text_verification.domain.ports import SourcePathResolver


@dataclass(frozen=True)
class CompatibilityExporter:
    file_type: FileType
    source_path_resolver: SourcePathResolver

    def export(
        self,
        document: DocumentModel,
        issues: list[Issue],
        target: Path,
        *,
        source_path: Path | None = None,
        track_changes: bool = False,
        modified_text: str | None = None,
    ) -> Path:
        resolved_source = self.source_path_resolver.resolve(
            document,
            source_path=source_path,
        )
        exported = export_original(
            resolved_source.path,
            self.file_type.value,
            [_replacement_for_issue(issue) for issue in issues],
            track_changes,
            original_text=document.text,
            modified_text=modified_text,
        )
        target.write_bytes(exported.content)
        return target


def _replacement_for_issue(issue: Issue) -> tuple[str, str, int, int]:
    if issue.suggestion is None:
        raise ExportError("Export requires a non-null suggestion for every issue.")
    if not issue.auto_fixable:
        raise ExportError("Export requires every issue to be auto-fixable.")
    return (
        issue.original,
        issue.suggestion,
        issue.start,
        issue.end,
    )
