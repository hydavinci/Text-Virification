from fastapi import APIRouter

from text_verification.api.routes.compatibility import router as compatibility_router
from text_verification.api.routes.health import router as health_router
from text_verification.api.routes.jobs import router as jobs_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health_router)
api_router.include_router(jobs_router)
api_router.include_router(compatibility_router)
