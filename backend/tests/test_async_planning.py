import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import TripPlanningFailure
from app.agents.llm import GroqIntentModel
from app.core.config import Settings
from app.core.exceptions import AppError
from app.core.rate_limiter import (
    ExternalCallBudget,
    PlanningAdmissionService,
)
from app.core.security import utc_now
from app.db.session import create_redis_client
from app.models.conversation import Conversation
from app.models.itinerary import Itinerary
from app.models.message import Message
from app.models.trip import Trip
from app.services.planning_service import PlanningStreamStore


def _csrf_headers(client: AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["csrf_token"]}


async def _signup_login(
    client: AsyncClient,
    payload: dict[str, str],
) -> None:
    assert (await client.post("/api/v1/auth/signup", json=payload)).status_code == 201
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert login.status_code == 200


async def _conversation(client: AsyncClient) -> str:
    response = await client.post(
        "/api/v1/conversations",
        json={},
        headers=_csrf_headers(client),
    )
    assert response.status_code == 201
    return response.json()["id"]


def _sse_events(text: str) -> list[tuple[str | None, dict[str, Any]]]:
    events: list[tuple[str | None, dict[str, Any]]] = []
    for block in text.split("\n\n"):
        if not block or block.startswith(":"):
            continue
        event_id: str | None = None
        data: str | None = None
        for line in block.splitlines():
            if line.startswith("id: "):
                event_id = line[4:]
            elif line.startswith("data: "):
                data = line[6:]
        if data is not None:
            events.append((event_id, json.loads(data)))
    return events


@pytest.mark.asyncio
async def test_sync_saved_mode_remains_unchanged(
    client: AsyncClient,
    valid_signup: dict[str, str],
) -> None:
    await _signup_login(client, valid_signup)
    conversation_id = await _conversation(client)

    response = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "Plan synchronously"},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 201
    assert response.json()["trip"]["status"] == "completed"
    assert "events_url" not in response.json()


@pytest.mark.asyncio
async def test_saved_async_stream_stages_resume_and_persists_result(
    client: AsyncClient,
    valid_signup: dict[str, str],
) -> None:
    await _signup_login(client, valid_signup)
    conversation_id = await _conversation(client)
    started = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages?async=true",
        json={"content": "Plan asynchronously"},
        headers=_csrf_headers(client),
    )

    assert started.status_code == 202
    body = started.json()
    assert body["status"] == "running"
    assert body["user_message"]["role"] == "user"
    assert body["events_url"].endswith(f"/{body['trip_id']}/events")

    stream = await client.get(body["events_url"])
    assert stream.status_code == 200
    assert stream.headers["cache-control"] == "no-store"
    assert stream.headers["x-accel-buffering"] == "no"
    events = _sse_events(stream.text)
    progress = [event for _, event in events if event["event"] == "progress"]
    assert [(event["stage"], event["status"]) for event in progress] == [
        ("intent", "started"),
        ("intent", "completed"),
        ("research", "started"),
        ("research", "degraded"),
        ("planning", "started"),
        ("planning", "completed"),
        ("validation", "started"),
        ("validation", "completed"),
        ("response", "started"),
        ("response", "completed"),
    ]
    assert events[-1][1] == {"event": "completed", "trip_id": body["trip_id"]}

    first_id = events[0][0]
    assert first_id is not None
    resumed = await client.get(
        body["events_url"],
        headers={"Last-Event-ID": first_id},
    )
    resumed_events = _sse_events(resumed.text)
    assert resumed_events
    assert all(event_id != first_id for event_id, _ in resumed_events)
    assert resumed_events[-1][1]["event"] == "completed"

    stored = await client.get(f"/api/v1/trips/{body['trip_id']}")
    assert stored.status_code == 200
    assert stored.json()["trip_id"] == body["trip_id"]


@pytest.mark.asyncio
async def test_saved_stream_hides_other_user_and_expired_conversation(
    client: AsyncClient,
    db_session: AsyncSession,
    valid_signup: dict[str, str],
) -> None:
    await _signup_login(client, valid_signup)
    conversation_id = await _conversation(client)
    started = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages?async=true",
        json={"content": "Private async plan"},
        headers=_csrf_headers(client),
    )
    events_url = started.json()["events_url"]

    await client.post("/api/v1/auth/logout", headers=_csrf_headers(client))
    second = {
        "name": "Second User",
        "email": "second-stream-user@example.com",
        "password": "A-strong-password-84",
        "confirm_password": "A-strong-password-84",
    }
    await _signup_login(client, second)
    assert (await client.get(events_url)).status_code == 404

    await db_session.execute(
        update(Conversation)
        .where(Conversation.id == UUID(conversation_id))
        .values(expires_at=utc_now() - timedelta(seconds=1))
    )
    await db_session.commit()
    await client.post("/api/v1/auth/logout", headers=_csrf_headers(client))
    await client.post(
        "/api/v1/auth/login",
        json={"email": valid_signup["email"], "password": valid_signup["password"]},
    )
    assert (await client.get(events_url)).status_code == 404


@pytest.mark.asyncio
async def test_temporary_async_stream_binding_full_trip_and_no_postgres(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    session_id = secrets.token_urlsafe(32)
    started = await client.post(
        "/api/v1/chat/temporary?async=true",
        json={"temp_session_id": session_id, "content": "Temporary async plan"},
    )
    assert started.status_code == 202
    body = started.json()
    token = body["temp_token"]
    assert token
    assert (
        await client.get(
            body["events_url"],
            params={"temp_session_id": session_id, "temp_token": secrets.token_urlsafe(32)},
        )
    ).status_code == 404

    stream = await client.get(
        body["events_url"],
        params={"temp_session_id": session_id, "temp_token": token},
    )
    assert stream.status_code == 200
    final = _sse_events(stream.text)[-1][1]
    assert final["event"] == "completed"
    assert final["trip"]["trip_id"] == body["trip_id"]
    assert await db_session.scalar(select(func.count(Conversation.id))) == 0
    assert await db_session.scalar(select(func.count(Message.id))) == 0
    assert await db_session.scalar(select(func.count(Trip.id))) == 0
    assert await db_session.scalar(select(func.count(Itinerary.id))) == 0


class TimeoutPlanner:
    async def run(self, **_kwargs: Any) -> Any:
        raise TripPlanningFailure(
            "Trip planning timed out",
            code="planning_timeout",
            public_message="Trip planning timed out. Please try again.",
        )


@pytest.mark.asyncio
async def test_async_timeout_publishes_safe_failed_event(
    app: FastAPI,
    client: AsyncClient,
    valid_signup: dict[str, str],
) -> None:
    app.state.trip_planner = TimeoutPlanner()
    await _signup_login(client, valid_signup)
    conversation_id = await _conversation(client)
    started = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages?async=true",
        json={"content": "PRIVATE TIMEOUT PROMPT"},
        headers=_csrf_headers(client),
    )

    events = _sse_events((await client.get(started.json()["events_url"])).text)
    assert events[-1][1] == {
        "event": "failed",
        "code": "planning_timeout",
        "message": "Trip planning timed out. Please try again.",
    }
    assert "PRIVATE TIMEOUT PROMPT" not in json.dumps(events)


@pytest.mark.asyncio
async def test_stream_emits_heartbeat_without_events(settings: Settings) -> None:
    configured = settings.model_copy(
        update={
            "planning_stream_heartbeat_seconds": 1,
            "planning_stream_max_seconds": 5,
        }
    )
    redis = create_redis_client(configured)
    streams = PlanningStreamStore(redis, configured)
    trip_id = uuid4()
    session_id = secrets.token_urlsafe(32)
    token = secrets.token_urlsafe(32)
    await streams.create_temporary(
        trip_id=trip_id,
        temp_session_id=session_id,
        temp_token=token,
    )

    generator = streams.event_stream(trip_id, last_event_id=None)
    assert await anext(generator) == ": heartbeat\n\n"
    await generator.aclose()
    await redis.aclose()


@pytest.mark.asyncio
async def test_stale_stream_emits_safe_interrupted_failure(settings: Settings) -> None:
    configured = settings.model_copy(update={"planning_stream_max_seconds": 1})
    redis = create_redis_client(configured)
    streams = PlanningStreamStore(redis, configured)
    trip_id = uuid4()
    session_id = secrets.token_urlsafe(32)
    token = secrets.token_urlsafe(32)
    await streams.create_temporary(
        trip_id=trip_id,
        temp_session_id=session_id,
        temp_token=token,
    )
    await redis.hset(
        streams.metadata_key(trip_id),
        mapping={"created_at": (datetime.now(UTC) - timedelta(seconds=2)).isoformat()},
    )

    generator = streams.event_stream(trip_id, last_event_id=None)
    event = await anext(generator)
    await generator.aclose()
    await redis.aclose()

    parsed = _sse_events(event)
    assert parsed[-1][1] == {
        "event": "failed",
        "code": "planning_interrupted",
        "message": "Planning stopped before completion. Please start a new run.",
    }


@pytest.mark.asyncio
async def test_planning_hourly_daily_and_concurrency_limits(
    settings: Settings,
) -> None:
    configured = settings.model_copy(
        update={
            "planning_runs_per_hour": 1,
            "planning_runs_per_day": 1,
            "planning_max_concurrent": 1,
        }
    )
    redis = create_redis_client(configured)
    admission = PlanningAdmissionService(redis, configured)
    user_id = uuid4()
    first = await admission.admit_saved(user_id)
    with pytest.raises(AppError) as active_error:
        await admission.admit_saved(user_id)
    assert active_error.value.status_code == 409

    with pytest.raises(AppError) as capacity_error:
        await admission.admit_temporary(
            client_ip="198.51.100.7",
            temp_session_id=secrets.token_urlsafe(32),
        )
    assert capacity_error.value.status_code == 429
    assert capacity_error.value.headers == {"Retry-After": "1"}
    await first.release()

    with pytest.raises(AppError) as quota_error:
        await admission.admit_saved(user_id)
    assert quota_error.value.status_code == 429
    assert int(quota_error.value.headers["Retry-After"]) > 0
    await redis.aclose()


@pytest.mark.asyncio
async def test_planning_counter_keys_never_contain_user_text(settings: Settings) -> None:
    redis = create_redis_client(settings)
    marker = "PRIVATE USER PROMPT NEVER IN COUNTERS"
    lease = await PlanningAdmissionService(redis, settings).admit_temporary(
        client_ip="203.0.113.9",
        temp_session_id=marker,
    )
    await lease.release()
    keys = [str(key) for key in await redis.keys("planning:*")]
    assert keys
    assert marker not in " ".join(keys)
    await redis.aclose()


class DenyGroqBudget(ExternalCallBudget):
    async def consume(self, service: Any) -> bool:
        assert service == "groq"
        return False


class NeverCalledCompletion:
    async def ainvoke(self, _input: Any) -> Any:
        raise AssertionError("Groq must not be called after budget exhaustion")


@pytest.mark.asyncio
async def test_groq_intent_budget_exhaustion_returns_safe_503(
    app: FastAPI,
    client: AsyncClient,
    settings: Settings,
    valid_signup: dict[str, str],
) -> None:
    from app.agents.graph import LangGraphTripPlanner

    groq_settings = settings.model_copy(
        update={"groq_api_key": SecretStr("placeholder-test-key")}
    )
    app.state.trip_planner = LangGraphTripPlanner(
        groq_settings,
        intent_model=GroqIntentModel(
            groq_settings,
            client=NeverCalledCompletion(),
            call_budget=DenyGroqBudget(),
        ),
    )
    await _signup_login(client, valid_signup)
    conversation_id = await _conversation(client)

    response = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "private budget prompt"},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "planning_intent_budget_exhausted"
    assert response.json()["error"]["message"] == (
        "Trip planning capacity is unavailable right now. Please try later."
    )
    assert "private budget prompt" not in response.text
