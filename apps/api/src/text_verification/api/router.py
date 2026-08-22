from fastapi import APIRouter

from text_verification.api.routes.analysis import router as analysis_router
from text_verification.api.routes.decisions import router as decisions_router
from text_verification.api.routes.exports import router as exports_router
from text_verification.api.routes.health import router as health_router
from text_verification.api.routes.jobs import router as jobs_router
from text_verification.api.routes.review_history import router as review_history_router
from text_verification.api.routes.versions import router as versions_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health_router)
api_router.include_router(jobs_router)
api_router.include_router(analysis_router)
api_router.include_router(versions_router)
api_router.include_router(decisions_router)
api_router.include_router(review_history_router)
api_router.include_router(exports_router)
