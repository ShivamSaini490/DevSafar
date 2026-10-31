
import asyncio
import secrets

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.tracing import temporary_chat_tracing_enabled
from app.models.conversation import Conversation
from app.models.itinerary import Itinerary
from app.models.message import Message
from app.models.trip import Trip
from app.services.temporary_chat_service import TEMPORARY_CHAT_KEY_PREFIX


def _session_id() -> str:
    return secrets.token_urlsafe(32)


@pytest.mark.asyncio
async def test_guest_temporary_chat_uses_redis_only_and_expires(
    client: AsyncClient,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    settings.temporary_chat_ttl_seconds = 1
    session_id = _session_id()
    first = await client.post(
        "/api/v1/chat/temporary",
        json={"temp_session_id": session_id, "content": "Guest trip idea"},
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["trip"]["status"] == "completed"
    assistant_summary = body["assistant_message"]
    assert assistant_summary.startswith("Feasibility: unknown.")
    assert "Main reason:" in assistant_summary
    assert "Known cost is INR 10,500 against a budget of INR 15,000." in assistant_summary
    assert 2 <= assistant_summary.count(". ") + assistant_summary.endswith(".") <= 3
    assert len(assistant_summary) <= 320
    assert body["temp_token"]
    assert body["context_message_count"] == 2
    assert await db_session.scalar(select(func.count(Conversation.id))) == 0
    assert await db_session.scalar(select(func.count(Message.id))) == 0
    assert await db_session.scalar(select(func.count(Trip.id))) == 0
    assert await db_session.scalar(select(func.count(Itinerary.id))) == 0

    await asyncio.sleep(1.1)
    expired = await client.post(
        "/api/v1/chat/temporary",
        json={
            "temp_session_id": session_id,
            "temp_token": body["temp_token"],
            "content": "Continue after expiry",
        },
    )
    assert expired.status_code == 404


@pytest.mark.asyncio
async def test_temporary_context_refreshes_ttl_and_is_bounded(
    client: AsyncClient,
    settings: Settings,
) -> None:
    settings.temporary_chat_ttl_seconds = 10
    settings.temporary_chat_max_messages = 4
    session_id = _session_id()
    first = await client.post(
        "/api/v1/chat/temporary",
        json={"temp_session_id": session_id, "content": "First"},
    )
    token = first.json()["temp_token"]
    await asyncio.sleep(1)
    second = await client.post(
        "/api/v1/chat/temporary",
        json={"temp_session_id": session_id, "temp_token": token, "content": "Second"},
    )
    third = await client.post(
        "/api/v1/chat/temporary",
        json={"temp_session_id": session_id, "temp_token": token, "content": "Third"},
    )
    assert second.status_code == 200
    assert third.status_code == 200
    assert second.json()["temp_token"] is None
    assert third.json()["context_message_count"] == 4

    redis = Redis.from_url(settings.redis_connection_url, decode_responses=True)
    keys = await redis.keys(f"{TEMPORARY_CHAT_KEY_PREFIX}:*")
    assert len(keys) == 1
    assert 8 <= await redis.ttl(keys[0]) <= 10
    assert len((await redis.get(keys[0]) or "").encode()) <= settings.temporary_chat_max_bytes
    await redis.aclose()


@pytest.mark.asyncio
async def test_one_tabs_token_cannot_access_another_tabs_context(client: AsyncClient) -> None:
    first_session = _session_id()
    second_session = _session_id()
    first = await client.post(
        "/api/v1/chat/temporary",
        json={"temp_session_id": first_session, "content": "First tab"},
    )
    second = await client.post(
        "/api/v1/chat/temporary",
        json={"temp_session_id": second_session, "content": "Second tab"},
    )
    wrong_token = await client.post(
        "/api/v1/chat/temporary",
        json={
            "temp_session_id": first_session,
            "temp_token": second.json()["temp_token"],
            "content": "Try crossing tabs",
        },
    )
    assert wrong_token.status_code == 404
    correct_token = await client.post(
        "/api/v1/chat/temporary",
        json={
            "temp_session_id": first_session,
            "temp_token": first.json()["temp_token"],
            "content": "Continue first tab",
        },
    )
    assert correct_token.status_code == 200
    assert correct_token.json()["context_message_count"] == 4


@pytest.mark.asyncio
async def test_signed_in_temporary_chat_requires_csrf_and_stays_temporary(
    client: AsyncClient,
    valid_signup: dict[str, str],
    db_session: AsyncSession,
) -> None:
    await client.post("/api/v1/auth/signup", json=valid_signup)
    await client.post(
        "/api/v1/auth/login",
        json={"email": valid_signup["email"], "password": valid_signup["password"]},
    )
    payload = {"temp_session_id": _session_id(), "content": "Signed-in temporary turn"}
    assert (await client.post("/api/v1/chat/temporary", json=payload)).status_code == 403
    response = await client.post(
        "/api/v1/chat/temporary",
        json=payload,
        headers={"X-CSRF-Token": client.cookies["csrf_token"]},
    )
    assert response.status_code == 200, response.text
    assert await db_session.scalar(select(func.count(Conversation.id))) == 0
    assert await db_session.scalar(select(func.count(Message.id))) == 0
    assert await db_session.scalar(select(func.count(Trip.id))) == 0
    assert await db_session.scalar(select(func.count(Itinerary.id))) == 0


@pytest.mark.asyncio
async def test_temporary_chat_rate_limits_per_ip_and_session(
    client: AsyncClient, settings: Settings
) -> None:
    settings.temporary_chat_rate_limit_per_ip = 1
    settings.temporary_chat_rate_limit_per_session = 100
    first = await client.post(
        "/api/v1/chat/temporary",
        json={"temp_session_id": _session_id(), "content": "First IP request"},
    )
    second = await client.post(
        "/api/v1/chat/temporary",
        json={"temp_session_id": _session_id(), "content": "Second IP request"},
    )
    assert first.status_code == 200
    assert second.status_code == 429

    settings.temporary_chat_rate_limit_per_ip = 100
    settings.temporary_chat_rate_limit_per_session = 1
    session_id = _session_id()
    initial = await client.post(
        "/api/v1/chat/temporary",
        json={"temp_session_id": session_id, "content": "First session request"},
    )
    limited = await client.post(
        "/api/v1/chat/temporary",
        json={
            "temp_session_id": session_id,
            "temp_token": initial.json()["temp_token"],
            "content": "Second session request",
        },
    )
    assert initial.status_code == 200
    assert limited.status_code == 429


def test_temporary_chat_tracing_is_always_disabled(settings: Settings) -> None:
    settings.langsmith_tracing = True
    assert temporary_chat_tracing_enabled(settings) is False
