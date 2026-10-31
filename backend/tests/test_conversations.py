
from datetime import timedelta
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import utc_now
from app.models.conversation import Conversation
from app.models.itinerary import Itinerary
from app.models.message import Message
from app.models.trip import Trip


async def _signup_and_login(client: AsyncClient, payload: dict[str, str]) -> None:
    signup = await client.post("/api/v1/auth/signup", json=payload)
    assert signup.status_code == 201, signup.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert login.status_code == 200, login.text


def _csrf_headers(client: AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["csrf_token"]}


@pytest.mark.asyncio
async def test_saved_conversation_crud_and_message_pagination(
    client: AsyncClient, valid_signup: dict[str, str]
) -> None:
    await _signup_and_login(client, valid_signup)
    created = await client.post(
        "/api/v1/conversations", json={}, headers=_csrf_headers(client)
    )
    assert created.status_code == 201, created.text
    conversation = created.json()
    assert conversation["title"] == "New trip"

    listed = await client.get("/api/v1/conversations")
    fetched = await client.get(f"/api/v1/conversations/{conversation['id']}")
    assert [item["id"] for item in listed.json()] == [conversation["id"]]
    assert fetched.json() == conversation

    renamed = await client.patch(
        f"/api/v1/conversations/{conversation['id']}",
        json={"title": "South India weekend"},
        headers=_csrf_headers(client),
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "South India weekend"

    turn = await client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        json={"content": "Plan a short trip"},
        headers=_csrf_headers(client),
    )
    assert turn.status_code == 201, turn.text
    assert turn.json()["trip"]["status"] == "completed"
    assistant_summary = turn.json()["assistant_message"]["content"]
    assert assistant_summary.startswith("Feasibility: unknown.")
    assert "Main reason:" in assistant_summary
    assert "Known cost is INR 10,500 against a budget of INR 15,000." in assistant_summary
    assert 2 <= assistant_summary.count(". ") + assistant_summary.endswith(".") <= 3
    assert len(assistant_summary) <= 320
    first_page = await client.get(
        f"/api/v1/conversations/{conversation['id']}/messages", params={"limit": 1}
    )
    second_page = await client.get(
        f"/api/v1/conversations/{conversation['id']}/messages",
        params={"limit": 1, "offset": 1},
    )
    assert [first_page.json()[0]["role"], second_page.json()[0]["role"]] == [
        "user",
        "assistant",
    ]
    assert (
        await client.get(
            f"/api/v1/conversations/{conversation['id']}/messages", params={"limit": 51}
        )
    ).status_code == 422

    deleted = await client.delete(
        f"/api/v1/conversations/{conversation['id']}", headers=_csrf_headers(client)
    )
    assert deleted.status_code == 204
    assert (await client.get(f"/api/v1/conversations/{conversation['id']}")).status_code == 404


@pytest.mark.asyncio
async def test_cross_user_access_is_hidden_as_not_found(
    client: AsyncClient, valid_signup: dict[str, str]
) -> None:
    await _signup_and_login(client, valid_signup)
    created = await client.post(
        "/api/v1/conversations", json={}, headers=_csrf_headers(client)
    )
    conversation_id = created.json()["id"]

    client.cookies.clear()
    other = {
        "name": "Other User",
        "email": "other@example.com",
        "password": "Other-strong-password-42",
        "confirm_password": "Other-strong-password-42",
    }
    await _signup_and_login(client, other)
    assert (await client.get("/api/v1/conversations")).json() == []
    assert (await client.get(f"/api/v1/conversations/{conversation_id}")).status_code == 404
    assert (
        await client.patch(
            f"/api/v1/conversations/{conversation_id}",
            json={"title": "Stolen"},
            headers=_csrf_headers(client),
        )
    ).status_code == 404
    assert (
        await client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            json={"content": "Can I access this?"},
            headers=_csrf_headers(client),
        )
    ).status_code == 404
    assert (
        await client.delete(
            f"/api/v1/conversations/{conversation_id}", headers=_csrf_headers(client)
        )
    ).status_code == 404


@pytest.mark.asyncio
async def test_expired_conversation_is_not_found_before_cleanup(
    client: AsyncClient,
    valid_signup: dict[str, str],
    db_session: AsyncSession,
) -> None:
    await _signup_and_login(client, valid_signup)
    created = await client.post(
        "/api/v1/conversations", json={}, headers=_csrf_headers(client)
    )
    conversation_id = UUID(created.json()["id"])
    await db_session.execute(
        update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(expires_at=utc_now() - timedelta(seconds=1))
    )
    await db_session.commit()

    assert (await client.get(f"/api/v1/conversations/{conversation_id}")).status_code == 404
    assert (await client.get("/api/v1/conversations")).json() == []
    assert (
        await client.get(f"/api/v1/conversations/{conversation_id}/messages")
    ).status_code == 404
    assert (
        await client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            json={"content": "This must not be stored"},
            headers=_csrf_headers(client),
        )
    ).status_code == 404


@pytest.mark.asyncio
async def test_posting_messages_does_not_extend_expiry(
    client: AsyncClient, valid_signup: dict[str, str]
) -> None:
    await _signup_and_login(client, valid_signup)
    created = await client.post(
        "/api/v1/conversations", json={}, headers=_csrf_headers(client)
    )
    before = created.json()["expires_at"]
    conversation_id = created.json()["id"]
    response = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "Keep the original expiry"},
        headers=_csrf_headers(client),
    )
    assert response.status_code == 201
    after = (await client.get(f"/api/v1/conversations/{conversation_id}")).json()[
        "expires_at"
    ]
    assert after == before


@pytest.mark.asyncio
async def test_account_deletion_cascades_conversations_and_messages(
    client: AsyncClient,
    valid_signup: dict[str, str],
    db_session: AsyncSession,
) -> None:
    await _signup_and_login(client, valid_signup)
    created = await client.post(
        "/api/v1/conversations", json={}, headers=_csrf_headers(client)
    )
    conversation_id = created.json()["id"]
    await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "Delete this with my account"},
        headers=_csrf_headers(client),
    )
    deleted = await client.request(
        "DELETE",
        "/api/v1/users/me",
        json={"password": valid_signup["password"]},
        headers=_csrf_headers(client),
    )
    assert deleted.status_code == 200, deleted.text
    assert await db_session.scalar(select(func.count(Conversation.id))) == 0
    assert await db_session.scalar(select(func.count(Message.id))) == 0
    assert await db_session.scalar(select(func.count(Trip.id))) == 0
    assert await db_session.scalar(select(func.count(Itinerary.id))) == 0
