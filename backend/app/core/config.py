import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, PrivateAttr, SecretStr, field_validator, model_validator
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

    _uses_ephemeral_auth_secret: bool = PrivateAttr(default=False)

    app_name: str = "DevSafar API"
    app_version: str = "0.1.0"
    environment: Literal["development", "test", "staging", "production"] = "development"
    debug: bool = False
    log_level: str = "INFO"
    secret_key: SecretStr | None = None
    access_token_minutes: int = Field(default=60, ge=5, le=1440)
    access_token_cookie_name: str = "access_token"
    csrf_cookie_name: str = "csrf_token"

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
    dev_otp_email_fallback_enabled: bool = False

    otp_expiry_minutes: int = Field(default=5, ge=1, le=30)
    otp_max_attempts: int = Field(default=5, ge=1, le=10)
    otp_resend_cooldown_seconds: int = Field(default=60, ge=30, le=3600)
    reset_grant_expiry_minutes: int = Field(default=10, ge=1, le=30)

    login_rate_limit_per_ip: int = Field(default=10, ge=1)
    login_rate_limit_per_email: int = Field(default=5, ge=1)
    login_rate_limit_window_seconds: int = Field(default=60, ge=1)
    otp_request_rate_limit_per_ip: int = Field(default=10, ge=1)
    otp_request_rate_limit_per_email: int = Field(default=5, ge=1)
    otp_request_rate_limit_window_seconds: int = Field(default=300, ge=1)
    otp_verify_rate_limit_per_ip: int = Field(default=20, ge=1)
    otp_verify_rate_limit_per_email: int = Field(default=10, ge=1)
    otp_verify_rate_limit_window_seconds: int = Field(default=300, ge=1)

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

    @model_validator(mode="after")
    def validate_security_settings(self) -> "Settings":
        secret_is_missing = (
            self.secret_key is None or not self.secret_key.get_secret_value().strip()
        )
        if self.environment in {"staging", "production"} and secret_is_missing:
            raise ValueError("SECRET_KEY must be configured outside development")
        if self.environment == "development" and secret_is_missing:
            self.secret_key = SecretStr(secrets.token_urlsafe(48))
            self._uses_ephemeral_auth_secret = True
        if self.environment != "development" and self.dev_otp_email_fallback_enabled:
            raise ValueError("DEV_OTP_EMAIL_FALLBACK_ENABLED is development-only")
        return self

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

    @property
    def secure_auth_cookies(self) -> bool:
        return self.environment != "development"

    @property
    def auth_secret(self) -> str:
        if self.secret_key is None:
            raise ValueError("SECRET_KEY is required for authentication operations")
        return self.secret_key.get_secret_value()

    @property
    def uses_ephemeral_auth_secret(self) -> bool:
        return self._uses_ephemeral_auth_secret

    def redaction_secret_values(self) -> tuple[str, ...]:
        optional_secrets = (
            self.secret_key,
            self.groq_api_key,
            self.qdrant_api_key,
            self.smtp_password,
            self.langsmith_api_key,
        )
        values = [
            self.postgres_password.get_secret_value(),
            self.redis_url.get_secret_value(),
        ]
        values.extend(
            secret.get_secret_value() for secret in optional_secrets if secret is not None
        )
        return tuple(value for value in values if value)


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
