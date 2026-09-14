from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from text_verification.application.readiness import get_readiness_checker
from text_verification.config import Settings, get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "text-verification-api",
        "version": "0.1.0",
    }


@router.get("/ready")
def ready(settings: Annotated[Settings, Depends(get_settings)]) -> JSONResponse:
    checks = get_readiness_checker(
        settings.database_url,
        settings.redis_url,
        settings.celery_broker_url,
        settings.preview_renderer_url,
    ).check()
    available = all(checks.values())
    return JSONResponse(
        status_code=200 if available else 503,
        content={
            "status": "ready" if available else "not_ready",
            "checks": {
                name: "ok" if passed else "unavailable" for name, passed in checks.items()
            },
        },
        headers={"Cache-Control": "no-store"},
    )
