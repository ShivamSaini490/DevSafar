import logging
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import BackgroundTasks, Request
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.otp import forgot_password
from app.core.config import Settings
from app.core.security import utc_now
from app.db.session import create_redis_client
from app.models.password_reset_otp import PasswordResetOtp
from app.schemas.otp import EmailRequest
from app.services.email_service import SmtpEmailSender
from tests.conftest import FakeEmailSender


class FailingEmailSender:
    def __init__(self) -> None:
        self.codes: list[str] = []

    async def send_password_reset_otp(
        self, *, recipient: str, code: str, expires_at: datetime
    ) -> None:
        del expires_at
        self.codes.append(code)
        raise RuntimeError(
            f"Unexpected EOF for {recipient}; otp={code}; password=background-secret"
        )


async def _signup(client: AsyncClient, payload: dict[str, str]) -> None:
    assert (await client.post("/api/v1/auth/signup", json=payload)).status_code == 201


async def _forgot(client: AsyncClient, email: str) -> dict[str, object]:
    response = await client.post("/api/v1/auth/forgot-password", json={"email": email})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_unknown_email_has_same_response(
    client: AsyncClient, valid_signup: dict[str, str]
) -> None:
    await _signup(client, valid_signup)
    known = await _forgot(client, valid_signup["email"])
    unknown = await _forgot(client, "unknown@example.com")
    assert known == unknown


@pytest.mark.asyncio
async def test_background_email_failure_keeps_generic_response_and_logs_redacted(
    app: Any,
    client: AsyncClient,
    valid_signup: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    await _signup(client, valid_signup)
    sender = FailingEmailSender()
    app.state.email_sender = sender

    with caplog.at_level(logging.WARNING):
        known = await client.post(
            "/api/v1/auth/forgot-password",
            json={"email": valid_signup["email"]},
        )
        unknown = await client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "unknown@example.com"},
        )

    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()
    assert len(sender.codes) == 1
    code = sender.codes[0]
    record = next(
        item for item in caplog.records if item.getMessage() == "OTP email delivery failed"
    )
    assert record.error_type == "RuntimeError"  # type: ignore[attr-defined]
    assert record.request_id == known.headers["X-Request-ID"]  # type: ignore[attr-defined]
    assert code not in caplog.text
    assert valid_signup["email"] not in caplog.text
    assert "background-secret" not in caplog.text


@pytest.mark.asyncio
async def test_email_send_is_deferred_until_background_tasks_run(
    client: AsyncClient,
    valid_signup: dict[str, str],
    fake_email_sender: FakeEmailSender,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    await _signup(client, valid_signup)
    background_tasks = BackgroundTasks()
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/forgot-password",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "state": {"request_id": "background-order-test"},
            "app": SimpleNamespace(state=SimpleNamespace()),
        }
    )
    redis = create_redis_client(settings)
    try:
        response = await forgot_password(
            payload=EmailRequest(email=valid_signup["email"]),
            request=request,
            background_tasks=background_tasks,
            db=db_session,
            redis=redis,
            settings=settings,
            email_sender=fake_email_sender,
        )
        assert response.message
        assert fake_email_sender.messages == []

        await background_tasks()
        assert len(fake_email_sender.messages) == 1
    finally:
        await redis.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("port", "smtp_use_tls", "expected_use_tls", "expected_start_tls"),
    [(587, False, False, True), (465, True, True, False)],
)
async def test_smtp_standard_ports_use_correct_tls_mode_and_timeout(
    monkeypatch: pytest.MonkeyPatch,
    port: int,
    smtp_use_tls: bool,
    expected_use_tls: bool,
    expected_start_tls: bool,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_send(_message: object, **kwargs: Any) -> tuple[dict[str, object], str]:
        captured.update(kwargs)
        return {}, "ok"

    monkeypatch.setattr("app.services.email_service.aiosmtplib.send", fake_send)
    settings = Settings(
        _env_file=None,
        environment="test",
        smtp_host="smtp.example.test",
        smtp_port=port,
        smtp_username="sender@example.test",
        smtp_password=SecretStr("placeholder-password"),
        smtp_use_tls=smtp_use_tls,
        smtp_from_email="sender@example.test",
        smtp_timeout_seconds=7.5,
    )

    await SmtpEmailSender(settings).send_password_reset_otp(
        recipient="recipient@example.test",
        code="123456",
        expires_at=utc_now(),
    )

    assert captured["use_tls"] is expected_use_tls
    assert captured["start_tls"] is expected_start_tls
    assert captured["timeout"] == 7.5


@pytest.mark.asyncio
async def test_expired_otp(
    client: AsyncClient,
    valid_signup: dict[str, str],
    fake_email_sender: FakeEmailSender,
    db_session: AsyncSession,
) -> None:
    await _signup(client, valid_signup)
    await _forgot(client, valid_signup["email"])
    code = fake_email_sender.latest_code(valid_signup["email"])
    await db_session.execute(
        update(PasswordResetOtp).values(expires_at=utc_now() - timedelta(seconds=1))
    )
    await db_session.commit()
    response = await client.post(
        "/api/v1/auth/verify-otp", json={"email": valid_signup["email"], "code": code}
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_five_attempts_lock_otp(
    client: AsyncClient, valid_signup: dict[str, str], fake_email_sender: FakeEmailSender
) -> None:
    await _signup(client, valid_signup)
    await _forgot(client, valid_signup["email"])
    code = fake_email_sender.latest_code(valid_signup["email"])
    for _ in range(5):
        response = await client.post(
            "/api/v1/auth/verify-otp",
            json={"email": valid_signup["email"], "code": "000000"},
        )
        assert response.status_code == 400
    locked = await client.post(
        "/api/v1/auth/verify-otp", json={"email": valid_signup["email"], "code": code}
    )
    assert locked.status_code == 400


@pytest.mark.asyncio
async def test_resend_cooldown_and_old_code_invalid(
    client: AsyncClient,
    valid_signup: dict[str, str],
    fake_email_sender: FakeEmailSender,
    db_session: AsyncSession,
) -> None:
    await _signup(client, valid_signup)
    await _forgot(client, valid_signup["email"])
    old_code = fake_email_sender.latest_code(valid_signup["email"])
    cooldown = await client.post("/api/v1/auth/resend-otp", json={"email": valid_signup["email"]})
    unknown = await client.post("/api/v1/auth/resend-otp", json={"email": "unknown@example.com"})
    assert cooldown.status_code == unknown.status_code == 200
    assert cooldown.json() == unknown.json()
    assert fake_email_sender.latest_code(valid_signup["email"]) == old_code
    await db_session.execute(
        update(PasswordResetOtp).values(resend_available_at=utc_now() - timedelta(seconds=1))
    )
    await db_session.commit()
    resent = await client.post("/api/v1/auth/resend-otp", json={"email": valid_signup["email"]})
    assert resent.status_code == 200
    assert fake_email_sender.latest_code(valid_signup["email"]) != old_code
    invalid = await client.post(
        "/api/v1/auth/verify-otp",
        json={"email": valid_signup["email"], "code": old_code},
    )
    assert invalid.status_code == 400


@pytest.mark.asyncio
async def test_consumed_otp_and_reset_grant_cannot_be_reused(
    client: AsyncClient, valid_signup: dict[str, str], fake_email_sender: FakeEmailSender
) -> None:
    await _signup(client, valid_signup)
    await _forgot(client, valid_signup["email"])
    payload = {
        "email": valid_signup["email"],
        "code": fake_email_sender.latest_code(valid_signup["email"]),
    }
    verified = await client.post("/api/v1/auth/verify-otp", json=payload)
    assert verified.status_code == 200
    assert (await client.post("/api/v1/auth/verify-otp", json=payload)).status_code == 400
    reset_payload = {
        "reset_grant": verified.json()["reset_grant"],
        "new_password": "A-new-strong-password-43",
        "confirm_password": "A-new-strong-password-43",
    }
    assert (await client.post("/api/v1/auth/reset-password", json=reset_payload)).status_code == 200
    assert (await client.post("/api/v1/auth/reset-password", json=reset_payload)).status_code == 400


@pytest.mark.asyncio
async def test_reset_revokes_all_sessions(
    client: AsyncClient, valid_signup: dict[str, str], fake_email_sender: FakeEmailSender
) -> None:
    await _signup(client, valid_signup)
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": valid_signup["email"], "password": valid_signup["password"]},
    )
    assert login.status_code == 200
    await _forgot(client, valid_signup["email"])
    verified = await client.post(
        "/api/v1/auth/verify-otp",
        json={
            "email": valid_signup["email"],
            "code": fake_email_sender.latest_code(valid_signup["email"]),
        },
    )
    reset = await client.post(
        "/api/v1/auth/reset-password",
        json={
            "reset_grant": verified.json()["reset_grant"],
            "new_password": "A-new-strong-password-44",
            "confirm_password": "A-new-strong-password-44",
        },
    )
    assert reset.status_code == 200
    assert (await client.get("/api/v1/users/me")).status_code == 401
