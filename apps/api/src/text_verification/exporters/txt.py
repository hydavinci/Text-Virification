from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

from text_verification.domain.documents import DocumentModel

from .replacements import Replacement, ReplacementPlan


class TxtExporter:
    def export(self, document: DocumentModel, plan: ReplacementPlan, target: Path) -> Path:
        replacements_by_block: dict[str, list[Replacement]] = defaultdict(list)
        for replacement in plan.applicable:
            replacements_by_block[replacement.block_id].append(replacement)

        rendered_blocks = [
            self._apply_replacements(
                block.text,
                replacements_by_block.get(block.block_id, []),
            )
            for block in document.blocks
        ]
        payload = self._normalize_trailing_newline("\n\n".join(rendered_blocks))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload, encoding="utf-8", newline="\n")
        return target

    def export_text(
        self,
        text: str,
        replacements: Sequence[Replacement],
        target: Path,
    ) -> Path:
        payload = self._normalize_trailing_newline(
            self._apply_replacements(text, replacements)
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload, encoding="utf-8", newline="\n")
        return target

    def _apply_replacements(
        self,
        text: str,
        replacements: Sequence[Replacement],
    ) -> str:
        rendered = text
        for replacement in sorted(
            replacements,
            key=lambda item: (item.start, item.end, str(item.issue_id)),
            reverse=True,
        ):
            rendered = (
                rendered[: replacement.start]
                + replacement.value
                + rendered[replacement.end :]
            )
        return rendered

    def _normalize_trailing_newline(self, text: str) -> str:
        return f"{text.rstrip('\r\n')}\n"
