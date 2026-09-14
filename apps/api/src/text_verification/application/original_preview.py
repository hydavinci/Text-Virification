from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from email.message import Message
from typing import IO
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from pydantic import ValidationError

from text_verification.domain.documents import DocumentModel, FileType
from text_verification.domain.review_layout import (
    MAX_LAYOUT_TEXT,
    LayoutRenderRequest,
    ReviewLayout,
)
from text_verification.infrastructure.storage import JobOwnedSourcePathResolver, JobStorage

MAX_PREVIEW_BYTES = 25 * 1024 * 1024
PREVIEW_TYPES = frozenset({
    FileType.DOCX, FileType.DOC, FileType.RTF, FileType.PDF, FileType.PNG, FileType.JPG,
})


class OriginalPreviewError(ValueError):
    def __init__(self, message: str, status_code: int = 422) -> None:
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True)
class OriginalPreview:
    content: bytes
    media_type: str


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Request, fp: IO[bytes], code: int, msg: str, headers: Message, newurl: str,
    ) -> None:
        return None


def _request_renderer(
    content: bytes, path: str, renderer_url: str, media_type: str,
) -> bytes:
    if not renderer_url:
        raise OriginalPreviewError("未配置文档渲染服务，请启动 Docker renderer。", 503)
    request = Request(
        f"{renderer_url.rstrip('/')}/{path}",
        data=content,
        headers={"Content-Type": (
            "application/json" if media_type == "application/json" else "application/octet-stream"
        )},
        method="POST",
    )
    # Original documents must not be forwarded through environment proxies or redirects.
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=120 if path.startswith("review/") else 55) as response:
            if response.headers.get_content_type() != media_type:
                raise OriginalPreviewError("渲染服务返回了无效的预览格式。")
            rendered: bytes = response.read(MAX_PREVIEW_BYTES + 1)
    except HTTPError as error:
        detail = error.read(2048)
        error.close()
        if error.code == 503:
            raise OriginalPreviewError("文档渲染服务繁忙或尚未就绪，请稍后重试。", 503) from error
        message = "版式预览转换失败；原文件未修改，修订仍保留。"
        try:
            parsed = json.loads(detail)
        except (ValueError, UnicodeDecodeError):
            parsed = None
        if isinstance(parsed, dict) and isinstance(parsed.get("detail"), str):
            message = parsed["detail"][:300]
        raise OriginalPreviewError(message, 413 if error.code == 413 else 422) from error
    except (URLError, TimeoutError, OSError) as error:
        raise OriginalPreviewError(
            "无法连接文档渲染服务，请确认 Docker renderer 已启动。", 503
        ) from error
    if len(rendered) > MAX_PREVIEW_BYTES:
        raise OriginalPreviewError("预览文件无效或超过 25 MiB 上限。")
    return rendered


def render_office(content: bytes, file_type: str, renderer_url: str) -> bytes:
    rendered = _request_renderer(content, f"render/{file_type}", renderer_url, "application/pdf")
    if not rendered.startswith(b"%PDF-"):
        raise OriginalPreviewError("预览文件无效。")
    return rendered


def build_review_preview(
    document: DocumentModel, storage: JobStorage, renderer_url: str, text: str,
) -> ReviewLayout:
    if document.file_type not in PREVIEW_TYPES:
        raise OriginalPreviewError("此格式使用文字审阅，不提供分页原版式预览。", 415)
    if len(document.text) > MAX_LAYOUT_TEXT:
        raise OriginalPreviewError("文档超过 20 万字符的版式预览上限。", 413)
    resolver = JobOwnedSourcePathResolver(storage, document.document_id, document.file_type)
    with resolver.open_verified_copy(document) as source:
        payload = LayoutRenderRequest(
            content=base64.b64encode(source.read_bytes()).decode("ascii"),
            original_text=document.text, text=text,
        )
    rendered = _request_renderer(
        payload.model_dump_json().encode("utf-8"),
        f"review/{document.file_type.value}", renderer_url, "application/json",
    )
    try:
        return ReviewLayout.model_validate_json(rendered)
    except ValidationError as error:
        raise OriginalPreviewError("渲染服务返回了无效的页面数据。") from error


def build_original_preview(
    document: DocumentModel, storage: JobStorage, renderer_url: str,
) -> OriginalPreview:
    if document.file_type not in PREVIEW_TYPES:
        raise OriginalPreviewError("此格式使用文字审阅，不提供分页原版式预览。", 415)
    resolver = JobOwnedSourcePathResolver(storage, document.document_id, document.file_type)
    with resolver.open_verified_copy(document) as source:
        content = source.read_bytes()
    if document.file_type in {FileType.DOCX, FileType.DOC, FileType.RTF}:
        return OriginalPreview(
            render_office(content, document.file_type.value, renderer_url), "application/pdf"
        )
    media_type = {
        FileType.PDF: "application/pdf",
        FileType.PNG: "image/png",
        FileType.JPG: "image/jpeg",
    }[document.file_type]
    return OriginalPreview(content, media_type)
