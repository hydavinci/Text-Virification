from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from text_verification.compatibility.exporters import export_original
from text_verification.domain.documents import DocumentModel, FileType
from text_verification.domain.issues import Issue


@dataclass(frozen=True)
class CompatibilityExporter:
    file_type: FileType

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
        resolved_source_path = source_path or Path(document.source_name)
        exported = export_original(
            resolved_source_path,
            self.file_type.value,
            [
                (
                    issue.original,
                    issue.suggestion or "",
                    issue.start,
                    issue.end,
                )
                for issue in issues
            ],
            track_changes,
            original_text=document.text,
            modified_text=modified_text,
        )
        target.write_bytes(exported.content)
        return target
