from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from text_verification.api.dependencies import get_db_session, get_job_storage
from text_verification.api.routes.jobs import get_job_result
from text_verification.application.original_preview import (
    OriginalPreviewError,
    build_original_preview,
    build_review_preview,
)
from text_verification.config import Settings, get_settings
from text_verification.domain.documents import DocumentModel
from text_verification.domain.review_layout import LayoutRevision
from text_verification.domain.verification import VerificationResult
from text_verification.infrastructure.storage import InvalidUpload, JobStorage

router = APIRouter(tags=["jobs"])


@router.get("/jobs/{job_id}/preview")
def get_original_preview(
    job_id: UUID,
    result: Annotated[VerificationResult, Depends(get_job_result)],
    session: Annotated[Session, Depends(get_db_session)],
    storage: Annotated[JobStorage, Depends(get_job_storage)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    document = DocumentModel.model_validate(
        result.model_dump(include=set(DocumentModel.model_fields))
    )
    try:
        preview = build_original_preview(document, storage, settings.preview_renderer_url)
    except OriginalPreviewError as error:
        raise HTTPException(
            error.status_code, detail={"code": "preview_unavailable", "message": str(error)}
        ) from error
    except FileNotFoundError as error:
        raise HTTPException(
            410, detail={"code": "source_expired", "message": "原文件已清理，无法预览原版式。"}
        ) from error
    except InvalidUpload as error:
        raise HTTPException(
            409, detail={"code": "source_invalid", "message": "原文件身份校验失败，无法预览。"}
        ) from error
    current = get_job_result(job_id, session)
    if current.source_version != result.source_version:
        raise HTTPException(
            409, detail={"code": "source_changed", "message": "原文件已变化，请重新打开预览。"}
        )
    return Response(
        preview.content,
        media_type=preview.media_type,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "inline",
            "Content-Security-Policy": "sandbox",
        },
    )


@router.post("/jobs/{job_id}/preview/layout")
def get_review_layout(
    job_id: UUID,
    revision: LayoutRevision,
    result: Annotated[VerificationResult, Depends(get_job_result)],
    session: Annotated[Session, Depends(get_db_session)],
    storage: Annotated[JobStorage, Depends(get_job_storage)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    if revision.source_version != result.source_version:
        raise HTTPException(409, detail={"message": "原文件版本不匹配，请重新打开文档。"})
    document = DocumentModel.model_validate(
        result.model_dump(include=set(DocumentModel.model_fields))
    )
    try:
        layout = build_review_preview(
            document, storage, settings.preview_renderer_url, revision.text,
        )
    except OriginalPreviewError as error:
        raise HTTPException(error.status_code, detail={"message": str(error)}) from error
    except FileNotFoundError as error:
        raise HTTPException(410, detail={"message": "原文件已清理，无法预览。"}) from error
    except InvalidUpload as error:
        raise HTTPException(409, detail={"message": "原文件身份校验失败，无法预览。"}) from error
    current = get_job_result(job_id, session)
    if current.source_version != revision.source_version:
        raise HTTPException(409, detail={"message": "原文件已变化，请重新打开预览。"})
    return Response(
        layout.model_dump_json(), media_type="application/json",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
