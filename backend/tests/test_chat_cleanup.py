
from datetime import timedelta
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import utc_now
from app.models.conversation import Conversation
from app.models.itinerary import Itinerary
from app.models.message import Message
from app.models.trip import Trip
from app.services.cleanup_service import CleanupCounts, CleanupService
from app.services.planning_service import PlanningStreamStore


def _csrf_headers(client: AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["csrf_token"]}


@pytest.mark.asyncio
async def test_cleanup_is_batched_and_idempotent(
    app: FastAPI,
    client: AsyncClient,
    valid_signup: dict[str, str],
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    assert (await client.post("/api/v1/auth/signup", json=valid_signup)).status_code == 201
    assert (
        await client.post(
            "/api/v1/auth/login",
            json={
                "email": valid_signup["email"],
                "password": valid_signup["password"],
            },
        )
    ).status_code == 200
    expired = await client.post(
        "/api/v1/conversations",
        json={"title": "Expired"},
        headers=_csrf_headers(client),
    )
    valid = await client.post(
        "/api/v1/conversations",
        json={"title": "Valid"},
        headers=_csrf_headers(client),
    )
    owner_id = UUID((await client.get("/api/v1/users/me")).json()["id"])
    trip_ids: dict[str, UUID] = {}
    for conversation_id in (expired.json()["id"], valid.json()["id"]):
        turn = await client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            json={"content": "A saved turn"},
            headers=_csrf_headers(client),
        )
        trip_ids[conversation_id] = UUID(turn.json()["trip"]["trip_id"])
    streams = PlanningStreamStore(app.state.redis, settings)
    for conversation_id, trip_id in trip_ids.items():
        await streams.create_saved(
            trip_id=trip_id,
            conversation_id=UUID(conversation_id),
            owner_id=owner_id,
        )
        await streams.publish_progress(trip_id, "intent", "started")
    await db_session.execute(
        update(Conversation)
        .where(Conversation.id == UUID(expired.json()["id"]))
        .values(expires_at=utc_now() - timedelta(seconds=1))
    )
    await db_session.commit()

    service = CleanupService(db_session, redis=app.state.redis)
    first = await service.delete_expired_conversations(batch_size=1)
    second = await service.delete_expired_conversations(batch_size=1)
    assert first == CleanupCounts(
        conversations=1, messages=2, trips=1, itineraries=1, redis_streams=1
    )
    assert second == CleanupCounts()
    assert await db_session.scalar(select(func.count(Conversation.id))) == 1
    assert await db_session.scalar(select(func.count(Message.id))) == 2
    assert await db_session.scalar(select(func.count(Trip.id))) == 1
    assert await db_session.scalar(select(func.count(Itinerary.id))) == 1
    assert await db_session.scalar(select(Conversation.title)) == "Valid"
    expired_trip_id = trip_ids[expired.json()["id"]]
    valid_trip_id = trip_ids[valid.json()["id"]]
    assert not await app.state.redis.exists(streams.metadata_key(expired_trip_id))
    assert not await app.state.redis.exists(streams.stream_key(expired_trip_id))
    assert await app.state.redis.exists(streams.metadata_key(valid_trip_id))
    assert await app.state.redis.exists(streams.stream_key(valid_trip_id))
