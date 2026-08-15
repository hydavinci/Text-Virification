from __future__ import annotations

import re
from pathlib import Path
from uuid import UUID

from text_verification.domain.documents import DocumentModel, FileType, ParseError, TextBlock


class TxtParser:
    supported_type = FileType.TXT

    def parse(
        self,
        source_path: Path,
        *,
        document_id: UUID,
        source_name: str,
    ) -> DocumentModel:
        data = source_path.read_bytes()
        if b"\x00" in data:
            raise ParseError("txt_binary_content", "无法解析文本文件。")

        text, encoding = self._decode(data)
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        paragraphs = [
            paragraph.strip()
            for paragraph in re.split(r"\n\s*\n", normalized)
            if paragraph.strip()
        ]

        blocks = [
            TextBlock(
                block_id=f"p-{paragraph_index + 1:06d}",
                kind="paragraph",
                text=paragraph,
                page=None,
                paragraph_index=paragraph_index,
                parent_id=None,
                style={},
                source_locator={"paragraph_index": paragraph_index},
            )
            for paragraph_index, paragraph in enumerate(paragraphs)
        ]

        return DocumentModel(
            document_id=document_id,
            file_type=self.supported_type,
            source_name=source_name,
            version=1,
            blocks=blocks,
            metadata={"encoding": encoding},
        )

    def _decode(self, data: bytes) -> tuple[str, str]:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            pass
        else:
            if data.startswith(b"\xef\xbb\xbf"):
                return text, "utf-8-sig"
            return text, "utf-8"

        for encoding in ("utf-8", "gb18030"):
            try:
                return data.decode(encoding), encoding
            except UnicodeDecodeError:
                continue

        raise ParseError("txt_decode_error", "无法解析文本文件。")
