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
    storage_root: Path = Path("./var/jobs")
    rules_root: Path = Path("./resources/rules")
    dictionaries_root: Path = Path("./resources/dictionaries")
    job_retention_hours: int = Field(default=24, ge=1)
    max_upload_bytes: int = Field(default=25 * 1024 * 1024, ge=1)
    cors_origins: str = "http://localhost:5173"


@lru_cache
def get_settings() -> Settings:
    return Settings()
