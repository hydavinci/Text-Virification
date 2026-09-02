from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = (
        "postgresql+psycopg://text_verification:text_verification"
        "@localhost:5432/text_verification"
    )
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = ""
    storage_root: Path = Path("./var/jobs")
    job_retention_hours: int = Field(default=24, ge=1)
    job_lease_seconds: int = Field(default=1200, gt=900, le=3600)
    max_upload_bytes: int = Field(default=25 * 1024 * 1024, ge=1)
    cors_origins: str = "http://localhost:5173"
    llm_api_key: str = ""
    llm_api_base: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_max_review: int = Field(default=40, ge=1, le=200)
    llm_context_radius: int = Field(default=50, ge=0, le=2_000)
    llm_timeout: float = Field(default=60.0, gt=0, le=300)
    llm_json_mode: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
