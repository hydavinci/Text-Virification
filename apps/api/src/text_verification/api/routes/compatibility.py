from __future__ import annotations

import ntpath
import posixpath
from datetime import datetime
from typing import Annotated
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response

from text_verification.compatibility.exporters import ExportError, export_original
from text_verification.compatibility.models import (
    ExportOriginalRequest,
    ReportRequest,
    Scenario,
)
from text_verification.compatibility.reports import generate_report_html
from text_verification.compatibility.service import (
    AnalysisInputError,
    analyze,
    formats,
    parse_banned_words,
    parse_glossary,
    parse_uploaded_file,
    scenarios,
)
from text_verification.compatibility.storage import (
    CompatibilityStorage,
    CompatibilityUploadError,
    CompatibilityUploadTooLarge,
)
from text_verification.config import Settings, get_settings

router = APIRouter(tags=["compatibility"])


@router.get("/scenarios")
def list_scenarios() -> dict[str, object]:
    return {"scenarios": scenarios()}


@router.get("/formats")
def list_formats() -> dict[str, object]:
    return {"formats": formats()}


@router.post("/analyze")
def analyze_content(
    settings: Annotated[Settings, Depends(get_settings)],
    text: Annotated[str | None, Form()] = None,
    file: Annotated[UploadFile | None, File()] = None,
    scenario: Annotated[Scenario, Form()] = Scenario.GENERAL,
    enable_security: Annotated[bool, Form()] = True,
    enable_sensitive: Annotated[bool, Form()] = True,
    enable_ad_extreme: Annotated[bool, Form()] = False,
    custom_glossary: Annotated[str, Form()] = "",
    banned_words: Annotated[str, Form()] = "",
) -> dict[str, object]:
    try:
        glossary = parse_glossary(custom_glossary)
        banned = parse_banned_words(banned_words)
    except AnalysisInputError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    if text is not None and text.strip():
        if len(text.encode("utf-8")) > settings.max_upload_bytes:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Text exceeds the configured maximum size.",
            )
        return analyze(
            text=text,
            filename="直接输入文本",
            file_id=None,
            file_extension=None,
            scenario=scenario,
            custom_glossary=glossary,
            banned_words=banned,
            enable_security=enable_security,
            enable_sensitive=enable_sensitive,
            enable_ad_extreme=enable_ad_extreme,
        )

    if file is None or not file.filename:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Please upload a file or provide non-empty text.",
        )

    storage = CompatibilityStorage(settings.storage_root, settings.max_upload_bytes)
    file_id = uuid4()
    try:
        stored = storage.save_stream(file_id, file.filename, file.file)
        extracted_text = parse_uploaded_file(stored.path, stored.extension)
    except CompatibilityUploadTooLarge as error:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, detail=str(error)) from error
    except (CompatibilityUploadError, AnalysisInputError, ValueError) as error:
        storage.delete(file_id)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    except Exception as error:
        storage.delete(file_id)
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"File parsing failed: {error}",
        ) from error

    return analyze(
        text=extracted_text,
        filename=stored.original_name,
        file_id=file_id,
        file_extension=stored.extension,
        scenario=scenario,
        custom_glossary=glossary,
        banned_words=banned,
        enable_security=enable_security,
        enable_sensitive=enable_sensitive,
        enable_ad_extreme=enable_ad_extreme,
    )


@router.post("/export")
def export_report(payload: ReportRequest) -> Response:
    content = generate_report_html(payload.model_dump()).encode("utf-8")
    return Response(
        content=content,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": _content_disposition("原文检查报告.html")},
    )


@router.post("/export-original")
def export_modified_original(
    payload: ExportOriginalRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    storage = CompatibilityStorage(settings.storage_root, settings.max_upload_bytes)
    try:
        source_path, extension = storage.resolve_source(payload.file_id)
        original_text = parse_uploaded_file(source_path, extension)
        exported = export_original(
            source_path,
            extension,
            [
                (
                    replacement.original,
                    replacement.suggestion,
                    replacement.position,
                    replacement.end_position,
                )
                for replacement in payload.replacements
            ],
            payload.track_changes,
            original_text=original_text,
            modified_text=payload.modified_text,
        )
    except (CompatibilityUploadError, ExportError, ValueError) as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Export failed: {error}",
        ) from error

    base_name = _safe_download_name(payload.filename)
    if "." in base_name:
        base_name = base_name.rsplit(".", 1)[0]
    timestamp = datetime.now().strftime("%m%d%H%M%S")
    download_name = f"{base_name}_修改版_{timestamp}.{exported.extension}"
    return Response(
        content=exported.content,
        media_type=exported.media_type,
        headers={"Content-Disposition": _content_disposition(download_name)},
    )


def _safe_download_name(filename: str) -> str:
    posix_name = posixpath.basename(filename)
    normalized = ntpath.basename(posix_name).replace("\r", "").replace("\n", "").strip()
    return normalized or "修改后文本"


def _content_disposition(filename: str) -> str:
    return f"attachment; filename*=UTF-8''{quote(filename, safe='')}"
