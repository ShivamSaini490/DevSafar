
import logging
import secrets
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI, Request
from httpx import AsyncClient, Response
from pydantic import SecretStr
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.rate_limiter import PlanningAdmissionService
from app.core.security import utc_now
from app.core.tracing import temporary_chat_tracing_enabled
from app.models.auth_session import AuthSession
from app.models.conversation import Conversation
from app.models.itinerary import Itinerary
from app.models.message import Message
from app.models.trip import Trip


def _csrf_headers(client: AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["csrf_token"]}


async def _signup_login(client: AsyncClient, payload: dict[str, str]) -> None:
    signup = await client.post("/api/v1/auth/signup", json=payload)
    assert signup.status_code == 201, signup.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert login.status_code == 200, login.text


def _assert_standard_error(response: Response, status_code: int, code: str) -> None:
    assert response.status_code == status_code
    body = response.json()
    assert body["error"]["code"] == code
    assert body["error"]["message"]
    assert body["error"]["request_id"]


@pytest.mark.asyncio
async def test_auth_cookie_body_csrf_tamper_and_password_session_revocation(
    client: AsyncClient,
    valid_signup: dict[str, str],
    db_session: AsyncSession,
) -> None:
    signup = await client.post("/api/v1/auth/signup", json=valid_signup)
    assert signup.status_code == 201
    first_login = await client.post(
        "/api/v1/auth/login",
        json={"email": valid_signup["email"], "password": valid_signup["password"]},
    )
    assert first_login.status_code == 200
    access_token = client.cookies["access_token"]
    first_csrf = client.cookies["csrf_token"]
    assert access_token not in first_login.text
    assert not {"access_token", "token", "jwt"}.intersection(first_login.json())

    set_cookies = first_login.headers.get_list("set-cookie")
    access_cookie = next(item for item in set_cookies if item.startswith("access_token="))
    csrf_cookie = next(item for item in set_cookies if item.startswith("csrf_token="))
    assert "httponly" in access_cookie.casefold()
    assert "samesite=lax" in access_cookie.casefold()
    assert "samesite=lax" in csrf_cookie.casefold()

    for method, path, payload in (
        ("PATCH", "/api/v1/users/me", {"name": "No CSRF"}),
        ("POST", "/api/v1/conversations", {"title": "No CSRF"}),
        ("POST", "/api/v1/auth/logout", None),
    ):
        response = await client.request(method, path, json=payload)
        _assert_standard_error(response, 403, "csrf_validation_failed")

    replacement = "x" if access_token[-1] != "x" else "y"
    client.cookies.set("access_token", f"{access_token[:-1]}{replacement}")
    _assert_standard_error(await client.get("/api/v1/users/me"), 401, "invalid_token")
    client.cookies.set("access_token", access_token)
    assert (await client.get("/api/v1/users/me")).status_code == 200

    second_login = await client.post(
        "/api/v1/auth/login",
        json={"email": valid_signup["email"], "password": valid_signup["password"]},
    )
    assert second_login.status_code == 200
    second_csrf = client.cookies["csrf_token"]
    changed = await client.post(
        "/api/v1/users/me/change-password",
        json={
            "current_password": valid_signup["password"],
            "new_password": "A-new-strong-password-84",
            "confirm_password": "A-new-strong-password-84",
        },
        headers={"X-CSRF-Token": second_csrf},
    )
    assert changed.status_code == 200
    revoked_count = await db_session.scalar(
        select(func.count(AuthSession.id)).where(AuthSession.revoked_at.is_not(None))
    )
    assert revoked_count == 2
    client.cookies.set("access_token", access_token)
    client.cookies.set("csrf_token", first_csrf)
    _assert_standard_error(await client.get("/api/v1/users/me"), 401, "invalid_session")


@pytest.mark.asyncio
async def test_cross_user_and_expired_resources_are_hidden_on_every_endpoint(
    client: AsyncClient,
    valid_signup: dict[str, str],
    db_session: AsyncSession,
) -> None:
    await _signup_login(client, valid_signup)
    created = await client.post(
        "/api/v1/conversations",
        json={"title": "Owner A"},
        headers=_csrf_headers(client),
    )
    conversation_id = created.json()["id"]
    started = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        params={"async": "true"},
        json={"content": "Plan a private trip"},
        headers=_csrf_headers(client),
    )
    assert started.status_code == 202, started.text
    trip_id = started.json()["trip_id"]
    events_url = started.json()["events_url"]
    stream = await client.get(events_url)
    assert stream.status_code == 200
    assert stream.headers["cache-control"] == "no-store"

    client.cookies.clear()
    other = {
        "name": "Owner B",
        "email": "owner-b-security@example.com",
        "password": "B-strong-password-42",
        "confirm_password": "B-strong-password-42",
    }
    await _signup_login(client, other)
    assert (await client.get("/api/v1/conversations")).json() == []
    hidden_responses = [
        await client.get(f"/api/v1/conversations/{conversation_id}"),
        await client.get(f"/api/v1/conversations/{conversation_id}/messages"),
        await client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            json={"content": "Cross-user write"},
            headers=_csrf_headers(client),
        ),
        await client.delete(
            f"/api/v1/conversations/{conversation_id}",
            headers=_csrf_headers(client),
        ),
        await client.get(f"/api/v1/trips/{trip_id}"),
        await client.get(events_url),
    ]
    assert [response.status_code for response in hidden_responses] == [404] * 6

    client.cookies.clear()
    login_a = await client.post(
        "/api/v1/auth/login",
        json={"email": valid_signup["email"], "password": valid_signup["password"]},
    )
    assert login_a.status_code == 200
    await db_session.execute(
        update(Conversation)
        .where(Conversation.id == UUID(conversation_id))
        .values(expires_at=utc_now() - timedelta(seconds=1))
    )
    await db_session.commit()
    expired_responses = [
        await client.get(f"/api/v1/conversations/{conversation_id}"),
        await client.get(f"/api/v1/conversations/{conversation_id}/messages"),
        await client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            json={"content": "Expired write"},
            headers=_csrf_headers(client),
        ),
        await client.delete(
            f"/api/v1/conversations/{conversation_id}",
            headers=_csrf_headers(client),
        ),
        await client.get(f"/api/v1/trips/{trip_id}"),
        await client.get(events_url),
    ]
    assert [response.status_code for response in expired_responses] == [404] * 6
    assert (await client.get("/api/v1/conversations")).json() == []


@pytest.mark.asyncio
async def test_account_deletion_removes_all_owned_graph_rows(
    client: AsyncClient,
    valid_signup: dict[str, str],
    db_session: AsyncSession,
) -> None:
    await _signup_login(client, valid_signup)
    conversation = await client.post(
        "/api/v1/conversations", json={}, headers=_csrf_headers(client)
    )
    turn = await client.post(
        f"/api/v1/conversations/{conversation.json()['id']}/messages",
        json={"content": "Persist graph rows"},
        headers=_csrf_headers(client),
    )
    assert turn.status_code == 201
    deleted = await client.request(
        "DELETE",
        "/api/v1/users/me",
        json={"password": valid_signup["password"]},
        headers=_csrf_headers(client),
    )
    assert deleted.status_code == 200
    for model in (Conversation, Message, Trip, Itinerary):
        assert await db_session.scalar(select(func.count(model.id))) == 0


@pytest.mark.asyncio
async def test_temporary_context_and_stream_tokens_are_tab_bound_and_non_persistent(
    client: AsyncClient,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    session_id = secrets.token_urlsafe(32)
    started = await client.post(
        "/api/v1/chat/temporary",
        params={"async": "true"},
        json={"temp_session_id": session_id, "content": "Private temporary trip"},
    )
    assert started.status_code == 202
    body = started.json()
    token = body["temp_token"]
    assert token
    assert (await client.get(body["events_url"])).status_code == 404
    assert (
        await client.get(
            body["events_url"],
            params={"temp_session_id": session_id, "temp_token": secrets.token_urlsafe(32)},
        )
    ).status_code == 404
    good_stream = await client.get(
        body["events_url"],
        params={"temp_session_id": session_id, "temp_token": token},
    )
    assert good_stream.status_code == 200
    wrong_context = await client.post(
        "/api/v1/chat/temporary",
        json={
            "temp_session_id": session_id,
            "temp_token": secrets.token_urlsafe(32),
            "content": "Read another tab",
        },
    )
    assert wrong_context.status_code == 404
    missing_token_new_context = await client.post(
        "/api/v1/chat/temporary",
        json={"temp_session_id": session_id, "content": "Start isolated context"},
    )
    assert missing_token_new_context.status_code == 200
    assert missing_token_new_context.json()["temp_token"] != token
    for model in (Conversation, Message, Trip, Itinerary):
        assert await db_session.scalar(select(func.count(model.id))) == 0
    settings.langsmith_tracing = True
    assert temporary_chat_tracing_enabled(settings) is False


@pytest.mark.asyncio
async def test_rate_limits_use_retry_after_standard_errors_and_admission_guards(
    app: FastAPI,
    client: AsyncClient,
    valid_signup: dict[str, str],
    settings: Settings,
) -> None:
    settings.login_rate_limit_per_ip = 1
    first = await client.post(
        "/api/v1/auth/login", json={"email": "unknown@example.com", "password": "wrong"}
    )
    second = await client.post(
        "/api/v1/auth/login", json={"email": "unknown@example.com", "password": "wrong"}
    )
    assert first.status_code == 401
    _assert_standard_error(second, 429, "rate_limit_exceeded")
    assert int(second.headers["Retry-After"]) > 0

    await app.state.redis.flushdb()
    settings.login_rate_limit_per_ip = 20
    settings.otp_request_rate_limit_per_ip = 1
    otp_first = await client.post(
        "/api/v1/auth/forgot-password", json={"email": "unknown@example.com"}
    )
    otp_second = await client.post(
        "/api/v1/auth/forgot-password", json={"email": "unknown@example.com"}
    )
    assert otp_first.status_code == 200
    _assert_standard_error(otp_second, 429, "rate_limit_exceeded")
    assert int(otp_second.headers["Retry-After"]) > 0

    await app.state.redis.flushdb()
    settings.otp_verify_rate_limit_per_ip = 1
    verify_payload = {"email": "unknown@example.com", "code": "123456"}
    assert (await client.post("/api/v1/auth/verify-otp", json=verify_payload)).status_code == 400
    verify_limited = await client.post("/api/v1/auth/verify-otp", json=verify_payload)
    _assert_standard_error(verify_limited, 429, "rate_limit_exceeded")

    await app.state.redis.flushdb()
    await _signup_login(client, valid_signup)
    conversation = await client.post(
        "/api/v1/conversations", json={}, headers=_csrf_headers(client)
    )
    user_id = UUID((await client.get("/api/v1/users/me")).json()["id"])
    admission = PlanningAdmissionService(app.state.redis, settings)
    active = await admission.admit_saved(user_id)
    already_running = await client.post(
        f"/api/v1/conversations/{conversation.json()['id']}/messages",
        json={"content": "Second active run"},
        headers=_csrf_headers(client),
    )
    _assert_standard_error(already_running, 409, "planning_already_running")
    await active.release()

    await app.state.redis.flushdb()
    settings.planning_max_concurrent = 1
    capacity = await admission.admit_temporary(
        client_ip="198.51.100.1", temp_session_id=secrets.token_urlsafe(32)
    )
    capacity_limited = await client.post(
        "/api/v1/chat/temporary",
        json={
            "temp_session_id": secrets.token_urlsafe(32),
            "content": "Capacity test",
        },
        headers=_csrf_headers(client),
    )
    _assert_standard_error(capacity_limited, 429, "planning_capacity_reached")
    assert capacity_limited.headers["Retry-After"] == "1"
    await capacity.release()


@pytest.mark.asyncio
async def test_input_bounds_plain_data_and_global_body_limit(
    client: AsyncClient,
) -> None:
    name_payload = "<script>alert(1)</script> ' OR 1=1 --"
    title_payload = "<img src=x onerror=alert(1)>; DROP TABLE trips; --"
    password = "A-strong-password-42"
    signup_payload = {
        "name": name_payload,
        "email": "plain-data-security@example.com",
        "password": password,
        "confirm_password": password,
    }
    await _signup_login(client, signup_payload)
    assert (await client.get("/api/v1/users/me")).json()["name"] == name_payload
    conversation = await client.post(
        "/api/v1/conversations",
        json={"title": title_payload},
        headers=_csrf_headers(client),
    )
    assert conversation.status_code == 201
    assert conversation.json()["title"] == title_payload
    fetched = await client.get(f"/api/v1/conversations/{conversation.json()['id']}")
    assert fetched.json()["title"] == title_payload

    overlong = await client.post(
        f"/api/v1/conversations/{conversation.json()['id']}/messages",
        json={"content": "x" * 4001},
        headers=_csrf_headers(client),
    )
    _assert_standard_error(overlong, 422, "validation_error")
    oversized = await client.post(
        "/api/v1/auth/login",
        content=b'{"email":"x@example.com","password":"' + b"x" * 1_100_000 + b'"}',
        headers={"Content-Type": "application/json"},
    )
    _assert_standard_error(oversized, 413, "request_body_too_large")


@pytest.mark.asyncio
async def test_security_headers_and_strict_credentialed_cors(
    client: AsyncClient,
    valid_signup: dict[str, str],
) -> None:
    health = await client.get("/api/v1/health")
    assert health.headers["x-content-type-options"] == "nosniff"
    assert health.headers["referrer-policy"] == "no-referrer"
    assert health.headers["x-frame-options"] == "DENY"
    assert health.headers["cache-control"] == "no-store"

    docs = await client.get("/docs")
    assert docs.headers["content-security-policy"] == "frame-ancestors 'none'"
    await _signup_login(client, valid_signup)
    assert (await client.get("/api/v1/users/me")).headers["cache-control"] == "no-store"

    allowed = await client.options(
        "/api/v1/users/me",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    assert allowed.headers["access-control-allow-credentials"] == "true"
    assert allowed.headers["access-control-allow-origin"] != "*"
    denied = await client.options(
        "/api/v1/users/me",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers


@pytest.mark.asyncio
async def test_configured_secrets_otp_and_tokens_do_not_leak_to_logs_or_bodies(
    app: FastAPI,
    client: AsyncClient,
    valid_signup: dict[str, str],
    settings: Settings,
    fake_email_sender: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings.smtp_password = SecretStr("synthetic-smtp-password-value")
    settings.groq_api_key = SecretStr("synthetic-groq-key-value")
    await _signup_login(client, valid_signup)
    access_token = client.cookies["access_token"]
    forgot = await client.post(
        "/api/v1/auth/forgot-password", json={"email": valid_signup["email"]}
    )
    assert forgot.status_code == 200
    otp = fake_email_sender.latest_code(valid_signup["email"])

    configured = settings.redaction_secret_values()

    @app.get("/_test/security-secret-scan")
    async def secret_failure(_request: Request) -> None:
        raise RuntimeError(
            " ".join(
                (
                    f"token={access_token}",
                    f"otp={otp}",
                    *(f"secret={value}" for value in configured),
                )
            )
        )

    with caplog.at_level(logging.ERROR):
        failed = await client.get("/_test/security-secret-scan")
    assert failed.status_code == 500
    scanned = "\n".join((forgot.text, failed.text, caplog.text))
    for secret_value in (*configured, otp, access_token):
        assert secret_value not in scanned
