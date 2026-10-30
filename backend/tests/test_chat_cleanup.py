
from datetime import timedelta
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import utc_now
from app.models.conversation import Conversation
from app.models.message import Message
from app.services.cleanup_service import CleanupCounts, CleanupService


def _csrf_headers(client: AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["csrf_token"]}


@pytest.mark.asyncio
async def test_cleanup_is_batched_and_idempotent(
    client: AsyncClient,
    valid_signup: dict[str, str],
    db_session: AsyncSession,
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
    for conversation_id in (expired.json()["id"], valid.json()["id"]):
        await client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            json={"content": "A saved turn"},
            headers=_csrf_headers(client),
        )
    await db_session.execute(
        update(Conversation)
        .where(Conversation.id == UUID(expired.json()["id"]))
        .values(expires_at=utc_now() - timedelta(seconds=1))
    )
    await db_session.commit()

    service = CleanupService(db_session)
    first = await service.delete_expired_conversations(batch_size=1)
    second = await service.delete_expired_conversations(batch_size=1)
    assert first == CleanupCounts(conversations=1, messages=2)
    assert second == CleanupCounts()
    assert await db_session.scalar(select(func.count(Conversation.id))) == 1
    assert await db_session.scalar(select(func.count(Message.id))) == 2
    assert await db_session.scalar(select(Conversation.title)) == "Valid"
