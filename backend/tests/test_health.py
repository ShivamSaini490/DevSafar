import logging
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import FastAPI, Request
from httpx import AsyncClient

import app.core.config as config_module
from app.core.config import Settings, get_settings
from app.core.dependencies import postgres_is_ready, redis_is_ready
from app.core.logging import (
    redact_exception_message,
    redact_sensitive_data,
    redact_sensitive_text,
)
from app.db.session import create_db_engine


def _override_readiness(app: FastAPI, *, postgres: bool, redis: bool) -> None:
    async def postgres_override() -> bool:
        return postgres

    async def redis_override() -> bool:
        return redis

    app.dependency_overrides[postgres_is_ready] = postgres_override
    app.dependency_overrides[redis_is_ready] = redis_override


async def test_health_is_independent_of_external_services(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"]


async def test_ready_reports_both_dependencies(app: FastAPI, client: AsyncClient) -> None:
    _override_readiness(app, postgres=True, redis=True)

    response = await client.get("/api/v1/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"postgres": True, "redis": True},
    }


@pytest.mark.parametrize(
    ("postgres", "redis"),
    [(False, True), (True, False), (False, False)],
)
async def test_ready_returns_public_safe_503(
    app: FastAPI,
    client: AsyncClient,
    postgres: bool,
    redis: bool,
) -> None:
    _override_readiness(app, postgres=postgres, redis=redis)

    response = await client.get("/api/v1/ready")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    assert response.json()["error"]["details"] == {"checks": {"postgres": postgres, "redis": redis}}
    assert response.json()["error"]["request_id"]


async def test_framework_errors_use_consistent_format(client: AsyncClient) -> None:
    response = await client.get("/missing")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert response.json()["error"]["message"] == "Not Found"


def test_settings_keep_external_secrets_optional_and_tracing_off() -> None:
    settings = Settings(_env_file=None, environment="test")

    assert settings.groq_api_key is None
    assert settings.qdrant_api_key is None
    assert settings.smtp_password is None
    assert settings.langsmith_api_key is None
    assert settings.langsmith_tracing is False


def test_smtp_inconsistent_tls_and_missing_credentials_warn_at_startup(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from app.main import create_app

    settings = Settings(
        _env_file=None,
        environment="test",
        smtp_host="smtp.example.test",
        smtp_port=587,
        smtp_use_tls=True,
        smtp_username="",
        smtp_password=None,
    )

    with caplog.at_level(logging.WARNING):
        create_app(settings)

    assert "SMTP port 587 requires STARTTLS; SMTP_USE_TLS should be false" in caplog.text
    assert "SMTP_HOST is configured but SMTP_USERNAME or SMTP_PASSWORD is empty" in caplog.text


def test_default_env_file_is_resolved_from_backend_root() -> None:
    expected = Path(config_module.__file__).resolve().parents[2] / ".env"

    assert expected == config_module.DEFAULT_ENV_FILE


async def test_settings_load_cwd_independent_env_and_build_asyncpg_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_file = tmp_path / "foundation-test.env"
    env_file.write_text(
        "\n".join(
            (
                "POSTGRES_HOST=127.0.0.1",
                "POSTGRES_PORT=5433",
                "POSTGRES_DB=devsafar",
                "POSTGRES_USER=devsafar",
                "POSTGRES_PASSWORD=p@ss:/# word",
            )
        ),
        encoding="utf-8",
    )
    unrelated_cwd = tmp_path / "unrelated-working-directory"
    unrelated_cwd.mkdir()

    for variable in (
        "ENVIRONMENT",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
    ):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setattr(config_module, "DEFAULT_ENV_FILE", env_file)
    monkeypatch.chdir(unrelated_cwd)
    get_settings.cache_clear()

    try:
        settings = get_settings()
        engine = create_db_engine(settings)
        try:
            assert engine.url.drivername == "postgresql+asyncpg"
            assert engine.url.host == "127.0.0.1"
            assert engine.url.port == 5433
            assert engine.url.username == "devsafar"
            assert engine.url.password == "p@ss:/# word"
            assert engine.url.database == "devsafar"
        finally:
            await engine.dispose()
    finally:
        get_settings.cache_clear()


async def test_postgres_probe_logs_redacted_diagnostic(
    caplog: pytest.LogCaptureFixture,
) -> None:
    password = "do-not-log-this"

    class FailingConnectionContext:
        async def __aenter__(self) -> None:
            raise RuntimeError(
                "connect failed for "
                f"postgresql+asyncpg://devsafar:{password}@127.0.0.1:5433/devsafar"
            )

        async def __aexit__(self, *_args: object) -> None:
            return None

    class FailingEngine:
        def connect(self) -> FailingConnectionContext:
            return FailingConnectionContext()

    request = cast(
        Request,
        SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    db_engine=FailingEngine(),
                    settings=Settings(_env_file=None, postgres_password=password),
                )
            )
        ),
    )

    with caplog.at_level(logging.WARNING):
        assert await postgres_is_ready(request) is False

    record = caplog.records[-1]
    assert record.error_type == "RuntimeError"  # type: ignore[attr-defined]
    assert record.error_message == "connect failed for [REDACTED_CONNECTION_URL]"  # type: ignore[attr-defined]
    assert password not in caplog.text
    assert "postgresql+asyncpg://" not in caplog.text


def test_structured_redaction_covers_sensitive_fields_and_text() -> None:
    payload = {
        "password": "correct-horse",
        "nested": {
            "otp": "123456",
            "access_token": "token-value",
            "cookie": "session=value",
            "email": "person@example.com",
        },
        "message": "Contact person@example.com with password=correct-horse",
    }

    redacted = redact_sensitive_data(payload)
    serialized = str(redacted)

    for sensitive_value in (
        "correct-horse",
        "123456",
        "token-value",
        "session=value",
        "person@example.com",
    ):
        assert sensitive_value not in serialized
    assert redact_sensitive_text("Authorization=Bearer abc.def") == "Authorization=[REDACTED]"
    assert (
        redact_exception_message(
            RuntimeError("database password=raw-value"),
            secret_values=("raw-value",),
        )
        == "database password=[REDACTED]"
    )
