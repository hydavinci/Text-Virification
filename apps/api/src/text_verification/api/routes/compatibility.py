from __future__ import annotations

import logging
import ntpath
import posixpath
from datetime import datetime
from typing import Annotated
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from pydantic import ValidationError

from text_verification.api.body_readers import (
    MAX_JSON_STRING_ESCAPE_FACTOR,
)
from text_verification.api.dependencies import get_verification_pipeline
from text_verification.api.report_reader import read_bounded_report_request
from text_verification.application import (
    VerificationCommand,
    VerificationError,
    VerificationPipeline,
)
from text_verification.compatibility.adapters import verification_result_to_legacy_response
from text_verification.compatibility.exporters import (
    ExportError,
    ExportTextLimitError,
    export_original,
)
from text_verification.compatibility.models import (
    ExportOriginalRequest,
    Scenario,
)
from text_verification.compatibility.reports import generate_report_html
from text_verification.compatibility.service import (
    AnalysisInputError,
    build_verification_options,
    direct_text_document_id,
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
from text_verification.domain.documents import (
    MAX_CANONICAL_RESULT_BLOCKS,
    MAX_CANONICAL_RESULT_TOTAL_CODEPOINTS,
    MAX_CANONICAL_RESULT_TOTAL_UTF8_BYTES,
    FileType,
)
from text_verification.domain.text_edits import MAX_REVISION_TEXT_UTF8_BYTES
from text_verification.domain.verification import VerificationExecutionMode, VerificationResult
from text_verification.infrastructure.document_storage import (
    UnsupportedFileType,
    validate_declared_mime,
)
from text_verification.parsers.errors import ParserError

router = APIRouter(tags=["compatibility"])

logger = logging.getLogger(__name__)
_DICTIONARY_UNAVAILABLE_DETAIL = "Verification dictionaries are unavailable."
MAX_COMPATIBILITY_EXPORT_REQUEST_BYTES = 32 * 1024 * 1024
MAX_COMPATIBILITY_REPORT_REQUEST_BYTES = (
    MAX_JSON_STRING_ESCAPE_FACTOR
    * MAX_CANONICAL_RESULT_TOTAL_UTF8_BYTES
    + MAX_COMPATIBILITY_EXPORT_REQUEST_BYTES
)


@router.get("/scenarios")
def list_scenarios() -> dict[str, object]:
    return {"scenarios": scenarios()}


@router.get("/formats")
def list_formats() -> dict[str, object]:
    return {"formats": formats()}


@router.post("/analyze")
def analyze_content(
    settings: Annotated[Settings, Depends(get_settings)],
    pipeline: Annotated[VerificationPipeline, Depends(get_verification_pipeline)],
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
        options = build_verification_options(
            scenario=scenario,
            custom_glossary=glossary,
            banned_words=banned,
            enable_security=enable_security,
            enable_sensitive=enable_sensitive,
            enable_ad_extreme=enable_ad_extreme,
        )
    except AnalysisInputError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    if text is not None and text.strip():
        if len(text.encode("utf-8")) > settings.max_upload_bytes:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Text exceeds the configured maximum size.",
            )
        command = VerificationCommand(
            document_id=direct_text_document_id(text),
            source_path=None,
            direct_text=text,
            source_name="直接输入文本",
            file_type=FileType.TXT,
            options=options,
            execution_mode=VerificationExecutionMode.SYNCHRONOUS,
        )
        result = _run_pipeline(pipeline, command)
        payload = verification_result_to_legacy_response(result)
        payload["file_id"] = None
        payload["file_ext"] = None
        return payload

    if file is None or not file.filename:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Please upload a file or provide non-empty text.",
        )

    storage = CompatibilityStorage(settings.storage_root, settings.max_upload_bytes)
    file_id = uuid4()
    try:
        stored = storage.save_stream(file_id, file.filename, file.file)
        validate_declared_mime(file.content_type, FileType(stored.extension))
    except CompatibilityUploadTooLarge as error:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, detail=str(error)) from error
    except UnsupportedFileType as error:
        storage.delete(file_id)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    except CompatibilityUploadError as error:
        storage.delete(file_id)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    try:
        command = VerificationCommand(
            document_id=file_id,
            source_path=stored.path,
            direct_text=None,
            source_name=stored.original_name,
            file_type=FileType(stored.extension),
            options=options,
            execution_mode=VerificationExecutionMode.SYNCHRONOUS,
        )
        result = _run_pipeline(pipeline, command)
        payload = verification_result_to_legacy_response(result)
    except HTTPException:
        _delete_failed_upload(storage, file_id)
        raise
    except Exception:
        _delete_failed_upload(storage, file_id)
        raise

    payload["file_id"] = str(file_id)
    payload["file_ext"] = f".{stored.extension}"
    return payload


@router.post("/export")
async def export_report(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    max_document_bytes = min(
        settings.max_upload_bytes,
        MAX_REVISION_TEXT_UTF8_BYTES,
    )
    max_aggregate_bytes = min(
        MAX_CANONICAL_RESULT_TOTAL_UTF8_BYTES,
        3 * max_document_bytes,
    )
    payload = await read_bounded_report_request(
        request,
        max_body_bytes=min(
            MAX_COMPATIBILITY_REPORT_REQUEST_BYTES,
            (
                MAX_JSON_STRING_ESCAPE_FACTOR
                * max_aggregate_bytes
                + MAX_COMPATIBILITY_EXPORT_REQUEST_BYTES
            ),
        ),
        max_retained_bytes=MAX_COMPATIBILITY_EXPORT_REQUEST_BYTES,
        max_document_utf8_bytes=max_document_bytes,
        max_blocks=MAX_CANONICAL_RESULT_BLOCKS,
        max_total_codepoints=MAX_CANONICAL_RESULT_TOTAL_CODEPOINTS,
        max_total_utf8_bytes=max_aggregate_bytes,
    )
    content = generate_report_html(payload.model_dump()).encode("utf-8")
    return Response(
        content=content,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": _content_disposition("原文检查报告.html")},
    )
@router.post("/export-original")
async def export_modified_original(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    payload = await _read_export_original_request(request)
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
            max_text_bytes=settings.max_upload_bytes,
        )
    except ExportTextLimitError as error:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, detail=str(error)) from error
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


async def _read_export_original_request(
    request: Request,
) -> ExportOriginalRequest:
    raw_content_length = request.headers.get("content-length")
    if raw_content_length is not None:
        try:
            content_length = int(raw_content_length)
        except ValueError:
            content_length = -1
        if content_length > MAX_COMPATIBILITY_EXPORT_REQUEST_BYTES:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Export request body exceeds the configured maximum size.",
            )

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_COMPATIBILITY_EXPORT_REQUEST_BYTES:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Export request body exceeds the configured maximum size.",
            )
        body.extend(chunk)
    try:
        return ExportOriginalRequest.model_validate_json(body)
    except ValidationError as error:
        errors = [
            {
                **item,
                "loc": ("body", *item["loc"]),
            }
            for item in error.errors(
                include_url=False,
                include_context=True,
                include_input=False,
            )
        ]
        raise RequestValidationError(errors) from error


def _safe_download_name(filename: str) -> str:
    posix_name = posixpath.basename(filename)
    normalized = ntpath.basename(posix_name).replace("\r", "").replace("\n", "").strip()
    return normalized or "修改后文本"


def _content_disposition(filename: str) -> str:
    return f"attachment; filename*=UTF-8''{quote(filename, safe='')}"


def _delete_failed_upload(storage: CompatibilityStorage, file_id: UUID) -> None:
    try:
        storage.delete(file_id)
    except Exception:
        logger.warning(
            "compatibility_upload_cleanup_failed",
            extra={"file_id": str(file_id)},
            exc_info=True,
        )


def _run_pipeline(
    pipeline: VerificationPipeline,
    command: VerificationCommand,
) -> VerificationResult:
    try:
        return pipeline.run(command)
    except VerificationError as error:
        raise _compatibility_http_error(error) from error


def _compatibility_http_error(error: VerificationError) -> HTTPException:
    if error.code == "ocr_required":
        return HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=error.message,
        )
    if error.code == "dictionary_load_failed":
        return HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=_DICTIONARY_UNAVAILABLE_DETAIL,
        )
    if error.code == "parser_failed":
        parser_error = error.__cause__
        if isinstance(parser_error, ParserError):
            detail = parser_error.compatibility_detail or str(parser_error)
            if parser_error.compatibility_detail_format == "direct":
                return HTTPException(status.HTTP_400_BAD_REQUEST, detail=detail)
            return HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"File parsing failed: {detail}",
            )
    if error.stage == "parsing":
        return HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"File parsing failed: {error}",
        )
    raise error
