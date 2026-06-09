"""Runtime configuration for the autonomous support agent."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    support_db_path: Path = Field(
        default=Path("data/support.db"),
        validation_alias="SUPPORT_DB_PATH",
    )
    support_db_seed_enabled: bool = Field(
        default=True,
        validation_alias="SUPPORT_DB_SEED_ENABLED",
    )
    environment: str = Field(default="local", validation_alias="ENVIRONMENT")
    database_upload_enabled: bool = Field(
        default=False,
        validation_alias="DATABASE_UPLOAD_ENABLED",
    )
    database_upload_password: str | None = Field(
        default=None,
        validation_alias="DATABASE_UPLOAD_PASSWORD",
    )
    langfuse_host: str = Field(default="http://localhost:3000", validation_alias="LANGFUSE_HOST")
    langfuse_public_key: str | None = Field(default=None, validation_alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: str | None = Field(default=None, validation_alias="LANGFUSE_SECRET_KEY")
    langfuse_tracing_enabled: bool = Field(default=True, validation_alias="LANGFUSE_TRACING_ENABLED")


def get_settings() -> Settings:
    """Return the current process settings."""

    settings = Settings()
    os.environ.setdefault("SUPPORT_DB_PATH", str(settings.support_db_path))
    os.environ.setdefault("SUPPORT_DB_SEED_ENABLED", str(settings.support_db_seed_enabled).lower())
    os.environ.setdefault("ENVIRONMENT", settings.environment)
    os.environ.setdefault("DATABASE_UPLOAD_ENABLED", str(settings.database_upload_enabled).lower())
    if settings.database_upload_password:
        os.environ.setdefault("DATABASE_UPLOAD_PASSWORD", settings.database_upload_password)
    os.environ.setdefault("LANGFUSE_HOST", settings.langfuse_host)
    if settings.langfuse_public_key:
        os.environ.setdefault("LANGFUSE_PUBLIC_KEY", settings.langfuse_public_key)
    if settings.langfuse_secret_key:
        os.environ.setdefault("LANGFUSE_SECRET_KEY", settings.langfuse_secret_key)
    return settings
