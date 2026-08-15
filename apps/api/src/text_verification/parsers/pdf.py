from __future__ import annotations

from pathlib import Path
from uuid import UUID

from pypdf import PdfReader

from text_verification.domain.documents import DocumentModel, FileType, ParseError, TextBlock


class PdfParser:
    supported_type = FileType.PDF

    def parse(
        self,
        source_path: Path,
        *,
        document_id: UUID,
        source_name: str,
    ) -> DocumentModel:
        try:
            reader = PdfReader(str(source_path))
        except Exception as error:
            raise ParseError("pdf_parse_error", "无法解析 PDF 文件。") from error

        if reader.is_encrypted:
            raise ParseError("pdf_encrypted", "PDF 已加密，暂不支持解析。")

        blocks: list[TextBlock] = []
        for page_number, page in enumerate(reader.pages, start=1):
            text = page.extract_text().strip()
            if not text:
                continue
            blocks.append(
                TextBlock(
                    block_id=f"pdf-{page_number:06d}",
                    kind="paragraph",
                    text=text,
                    page=page_number,
                    paragraph_index=None,
                    parent_id=None,
                    style={},
                    source_locator={"page": page_number},
                )
            )

        if not blocks:
            raise ParseError(
                "pdf_no_extractable_text",
                "PDF 中没有可提取的文本，请使用包含文本层的 PDF。",
            )

        return DocumentModel(
            document_id=document_id,
            file_type=self.supported_type,
            source_name=source_name,
            version=1,
            blocks=blocks,
            metadata={"page_count": len(reader.pages)},
        )
