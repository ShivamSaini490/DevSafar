from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import utc_now
from app.models.password_reset_otp import PasswordResetOtp
from tests.conftest import FakeEmailSender


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
    assert cooldown.status_code == 429
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
