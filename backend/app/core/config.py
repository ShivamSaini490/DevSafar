import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = BACKEND_ROOT / ".env"


class Settings(BaseSettings):
    """Application settings loaded from environment variables and an explicit env file.

    Environment variables take precedence over values in the env file. Callers can
    pass ``_env_file=None`` when dotenv loading must be disabled, such as in tests.
    """

    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra="ignore",
        env_prefix="",
    )

    app_name: str = "DevSafar API"
    app_version: str = "0.1.0"
    environment: Literal["development", "test", "staging", "production"] = "development"
    debug: bool = False
    log_level: str = "INFO"

    postgres_host: str = "127.0.0.1"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_db: str = "devsafar"
    postgres_user: str = "devsafar"
    postgres_password: SecretStr = SecretStr("replace-with-local-dev-password")

    redis_url: SecretStr = SecretStr("redis://127.0.0.1:6379/0")

    groq_api_key: SecretStr | None = None
    qdrant_url: str | None = None
    qdrant_api_key: SecretStr | None = None

    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_use_tls: bool = True
    smtp_from_email: str | None = None

    langsmith_tracing: bool = False
    langsmith_api_key: SecretStr | None = None
    langsmith_project: str = "devsafar"
    langsmith_endpoint: str = "https://api.smith.langchain.com"

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        normalized = value.upper()
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        if normalized not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}")
        return normalized

    @property
    def database_url(self) -> str:
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        ).render_as_string(hide_password=False)

    @property
    def redis_connection_url(self) -> str:
        return self.redis_url.get_secret_value()


@lru_cache
def get_settings() -> Settings:
    env_file: Path | None = (
        None if os.getenv("ENVIRONMENT", "").lower() == "test" else DEFAULT_ENV_FILE
    )
    # pydantic-settings supports these runtime init keywords, but its mypy-generated
    # Settings signature does not expose them.
    return Settings(  # type: ignore[call-arg]
        _env_file=env_file,
        _env_file_encoding="utf-8",
    )
