from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from text_verification.api.errors import handle_request_validation_error
from text_verification.api.router import api_router
from text_verification.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="text-verification", version="0.1.0")
    app.add_exception_handler(
        RequestValidationError,
        handle_request_validation_error,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Content-Type", "Last-Event-ID"],
    )
    app.include_router(api_router)
    return app


app = create_app()
