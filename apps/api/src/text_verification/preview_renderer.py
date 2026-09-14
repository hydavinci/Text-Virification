from __future__ import annotations

import asyncio
import base64
import binascii
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from text_verification.application.original_preview import OriginalPreviewError
from text_verification.application.review_layout import render_review_document
from text_verification.compatibility.parser import (
    _conversion_environment,
    _run_conversion_process,
)
from text_verification.domain.review_layout import MAX_RENDER_REQUEST_BYTES, LayoutRenderRequest
from text_verification.infrastructure.storage import InvalidUpload, JobStorage

MAX_PREVIEW_BYTES = 25 * 1024 * 1024
OFFICE_TYPES = frozenset({"docx", "doc", "rtf"})
app = FastAPI(title="Local document renderer", docs_url=None, redoc_url=None)
conversion_lock = asyncio.Lock()


class PreviewRenderError(ValueError):
    pass


def validate_source(content: bytes, file_type: str) -> None:
    with TemporaryDirectory(prefix="preview-validation-") as directory:
        JobStorage(Path(directory), MAX_PREVIEW_BYTES).save_bytes(
            uuid4(), f"source.{file_type}", content
        )


def convert_document(content: bytes, file_type: str, target_type: str = "pdf") -> bytes:
    if target_type not in {"pdf", "docx"}:
        raise PreviewRenderError("Unsupported conversion target.")
    office = shutil.which("soffice") or shutil.which("libreoffice")
    if office is None:
        raise PreviewRenderError("LibreOffice is unavailable in the renderer.")
    with TemporaryDirectory(prefix="document-preview-") as directory:
        workspace = Path(directory)
        source = workspace / f"source.{file_type}"
        source.write_bytes(content)
        profile = workspace / "profile"
        user_profile = profile / "user"
        user_profile.mkdir(parents=True)
        (user_profile / "registrymodifications.xcu").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<oor:items xmlns:oor="http://openoffice.org/2001/registry">'
            '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
            '<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop>'
            '</item><item oor:path="/org.openoffice.Office.Writer/Content/Update">'
            '<prop oor:name="Link" oor:op="fuse"><value>0</value></prop>'
            '</item></oor:items>',
            encoding="utf-8",
        )
        output = workspace / f"source.{target_type}"
        try:
            _run_conversion_process(
                [
                    office,
                    f"-env:UserInstallation={profile.as_uri()}",
                    "--headless", "--nologo", "--nodefault", "--norestore",
                    "--convert-to",
                    (
                        "pdf:writer_pdf_Export"
                        if target_type == "pdf" else "docx:Office Open XML Text"
                    ),
                    "--outdir", str(workspace), str(source),
                ],
                output_path=output,
                cwd=workspace,
                environment=_conversion_environment(workspace),
                timeout_seconds=45,
            )
        except (OSError, ValueError) as error:
            raise PreviewRenderError(
                "Document conversion failed or timed out; the original file is unchanged."
            ) from error
        if output.stat().st_size > MAX_PREVIEW_BYTES:
            raise PreviewRenderError("The rendered preview exceeds the size limit.")
        rendered = output.read_bytes()
        if not rendered.startswith(b"%PDF-" if target_type == "pdf" else b"PK"):
            raise PreviewRenderError("The renderer did not produce the requested format.")
        return rendered


@app.get("/health")
def health() -> dict[str, str]:
    if not (shutil.which("soffice") or shutil.which("libreoffice")):
        raise HTTPException(503, "LibreOffice is unavailable.")
    return {"status": "ok"}


@app.post("/render/{file_type}")
async def render(file_type: str, request: Request) -> Response:
    if file_type not in OFFICE_TYPES:
        raise HTTPException(415, "This file type does not use the Office renderer.")
    if conversion_lock.locked():
        raise HTTPException(503, "The renderer is busy. Try again shortly.")
    # Bound both the upload and conversion; no unbounded queue of document bodies.
    async with conversion_lock:
        content = bytearray()
        async for chunk in request.stream():
            if len(content) + len(chunk) > MAX_PREVIEW_BYTES:
                raise HTTPException(413, "Document exceeds the preview size limit.")
            content.extend(chunk)
        try:
            source = bytes(content)
            await run_in_threadpool(validate_source, source, file_type)
            pdf = await run_in_threadpool(convert_document, source, file_type)
        except InvalidUpload as error:
            raise HTTPException(422, "Invalid document for layout preview.") from error
        except PreviewRenderError as error:
            raise HTTPException(422, str(error)) from error
    return Response(
        pdf, media_type="application/pdf",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@app.post("/review/{file_type}")
async def review(file_type: str, request: Request) -> Response:
    if file_type not in OFFICE_TYPES | {"pdf", "png", "jpg"}:
        raise HTTPException(415, "Unsupported review format.")
    if conversion_lock.locked():
        raise HTTPException(503, "The renderer is busy. Try again shortly.")
    async with conversion_lock:
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_RENDER_REQUEST_BYTES:
                raise HTTPException(413, "Review request exceeds the size limit.")
            body.extend(chunk)
        try:
            payload = LayoutRenderRequest.model_validate_json(bytes(body))
            content = base64.b64decode(payload.content, validate=True)
            await run_in_threadpool(validate_source, content, file_type)
            layout = await run_in_threadpool(
                render_review_document, content, file_type, payload.original_text,
                payload.text, convert=convert_document,
            )
        except (ValidationError, binascii.Error, InvalidUpload) as error:
            raise HTTPException(422, "Invalid review document.") from error
        except OriginalPreviewError as error:
            raise HTTPException(error.status_code, str(error)) from error
        except PreviewRenderError as error:
            raise HTTPException(422, str(error)) from error
    return Response(
        layout.model_dump_json(), media_type="application/json",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
