import logging
import os
import secrets
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.config as config_module
from app.core.config import Settings, get_settings
from app.core.security import create_access_token, generate_session_secret, utc_now
from app.models.auth_session import AuthSession


async def _signup(client: AsyncClient, payload: dict[str, str]) -> None:
    response = await client.post("/api/v1/auth/signup", json=payload)
    assert response.status_code == 201, response.text


async def _login(client: AsyncClient, payload: dict[str, str]) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert response.status_code == 200, response.text
    assert "access_token" not in response.json()


def _csrf_headers(client: AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["csrf_token"]}


@pytest.mark.asyncio
async def test_signup_login_logout_and_protected_route(
    client: AsyncClient, valid_signup: dict[str, str]
) -> None:
    await _signup(client, valid_signup)
    await _login(client, valid_signup)
    assert (await client.get("/api/v1/users/me")).status_code == 200
    assert "access_token" in client.cookies
    response = await client.post("/api/v1/auth/logout", headers=_csrf_headers(client))
    assert response.status_code == 200
    assert (await client.get("/api/v1/users/me")).status_code == 401


@pytest.mark.asyncio
async def test_wrong_password_and_duplicate_email(
    client: AsyncClient, valid_signup: dict[str, str]
) -> None:
    await _signup(client, valid_signup)
    assert (await client.post("/api/v1/auth/signup", json=valid_signup)).status_code == 409
    wrong = await client.post(
        "/api/v1/auth/login",
        json={"email": valid_signup["email"], "password": "wrong-password"},
    )
    assert wrong.status_code == 401


@pytest.mark.asyncio
async def test_missing_expired_and_revoked_tokens(
    client: AsyncClient,
    valid_signup: dict[str, str],
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    assert (await client.get("/api/v1/users/me")).status_code == 401
    await _signup(client, valid_signup)
    await _login(client, valid_signup)
    me = await client.get("/api/v1/users/me")
    expired, _ = create_access_token(
        user_id=UUID(me.json()["id"]),
        sid=generate_session_secret(),
        jti=generate_session_secret(),
        settings=settings,
        now=utc_now() - timedelta(hours=2),
    )
    client.cookies.clear()
    client.cookies.set("access_token", expired)
    assert (await client.get("/api/v1/users/me")).status_code == 401
    await _login(client, valid_signup)
    session_id = await db_session.scalar(
        select(AuthSession.id).order_by(AuthSession.created_at.desc()).limit(1)
    )
    await db_session.execute(
        update(AuthSession).where(AuthSession.id == session_id).values(revoked_at=utc_now())
    )
    await db_session.commit()
    assert (await client.get("/api/v1/users/me")).status_code == 401


@pytest.mark.asyncio
async def test_csrf_is_required(client: AsyncClient, valid_signup: dict[str, str]) -> None:
    await _signup(client, valid_signup)
    await _login(client, valid_signup)
    response = await client.post("/api/v1/auth/logout")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_validation_failed"


@pytest.mark.asyncio
async def test_login_rate_limit(
    client: AsyncClient, valid_signup: dict[str, str], settings: Settings
) -> None:
    settings.login_rate_limit_per_ip = 1
    first = await client.post(
        "/api/v1/auth/login", json={"email": valid_signup["email"], "password": "wrong"}
    )
    second = await client.post(
        "/api/v1/auth/login", json={"email": valid_signup["email"], "password": "wrong"}
    )
    assert first.status_code == 401
    assert second.status_code == 429
    assert int(second.headers["Retry-After"]) > 0


@pytest.mark.asyncio
async def test_real_app_settings_path_login_without_development_secret(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    safe_env_file = tmp_path / "development.env"
    safe_env_file.write_text("", encoding="utf-8")
    monkeypatch.setattr(config_module, "DEFAULT_ENV_FILE", safe_env_file)
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv(
        "REDIS_URL",
        os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:6379/15"),
    )
    get_settings.cache_clear()

    from app.main import create_app

    application = create_app()
    transport = ASGITransport(app=application)
    unique_email = f"real-settings-{UUID(int=secrets.randbits(128)).hex}@example.com"
    password = f"A-{secrets.token_urlsafe(24)}"
    signup_payload = {
        "name": "Real Settings",
        "email": unique_email,
        "password": password,
        "confirm_password": password,
    }
    try:
        async with (
            application.router.lifespan_context(application),
            AsyncClient(transport=transport, base_url="http://testserver") as real_client,
        ):
            assert application.state.settings.uses_ephemeral_auth_secret is True
            signup = await real_client.post("/api/v1/auth/signup", json=signup_payload)
            login = await real_client.post(
                "/api/v1/auth/login",
                json={"email": unique_email, "password": password},
            )
        assert signup.status_code == 201, signup.text
        assert login.status_code == 200, login.text
        assert "access_token" not in login.json()
        assert "access_token" in login.cookies
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_unexpected_error_is_logged_redacted_and_public_response_is_safe(
    app: FastAPI,
    client: AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "synthetic-secret-that-must-not-leak"

    @app.get("/_test/unexpected")
    async def unexpected_error(_request: Request) -> None:
        raise RuntimeError(f"password={secret}")

    with caplog.at_level(logging.ERROR):
        response = await client.get("/_test/unexpected")

    body = response.json()
    request_id = body["error"]["request_id"]
    assert response.status_code == 500
    assert body == {
        "error": {
            "code": "internal_server_error",
            "message": "An unexpected error occurred.",
            "request_id": request_id,
        }
    }
    assert response.headers["X-Request-ID"] == request_id
    record = next(
        record
        for record in caplog.records
        if record.getMessage() == "Unhandled application error"
    )
    assert record.request_id == request_id  # type: ignore[attr-defined]
    assert "Traceback (most recent call last)" in record.traceback  # type: ignore[attr-defined]
    assert secret not in record.traceback  # type: ignore[attr-defined]
    assert "password=[REDACTED]" in record.traceback  # type: ignore[attr-defined]
    assert secret not in response.text
    assert secret not in caplog.text
