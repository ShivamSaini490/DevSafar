import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from conftest import FakeIntentModel
from fastapi import FastAPI
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import LangGraphTripPlanner
from app.agents.llm import GroqIntentModel
from app.core.config import Settings
from app.core.security import utc_now
from app.models.conversation import Conversation
from app.models.itinerary import Itinerary
from app.models.trip import Trip


class FakeIntentCompletionClient:
    def __init__(self, *responses: Any) -> None:
        self.responses = list(responses)
        self.calls = 0
        self.inputs: list[object] = []

    async def ainvoke(self, input: object) -> Any:
        self.inputs.append(input)
        response = self.responses[self.calls]
        self.calls += 1
        if isinstance(response, BaseException):
            raise response
        return response


class FakeGroqBadRequest(RuntimeError):
    def __init__(self, body: dict[str, Any]) -> None:
        super().__init__("Groq request failed")
        self.status_code = 400
        self.body = body


def _configured_groq_settings(
    settings: Settings,
    *,
    api_key: str,
) -> Settings:
    return settings.model_copy(
        update={
            "groq_api_key": SecretStr(api_key),
            "groq_model": "openai/gpt-oss-120b",
        }
    )


def _install_groq_intent_model(
    app: FastAPI,
    settings: Settings,
    fake_client: FakeIntentCompletionClient,
    *,
    api_key: str,
    current_date: date | None = None,
) -> None:
    groq_settings = _configured_groq_settings(settings, api_key=api_key)
    effective_date = current_date or date(2026, 10, 30)
    app.state.trip_planner = LangGraphTripPlanner(
        groq_settings,
        intent_model=GroqIntentModel(
            groq_settings,
            client=fake_client,
            today_provider=lambda: effective_date,
        ),
    )


async def _signup_and_login(client: AsyncClient, payload: dict[str, str]) -> None:
    assert (await client.post("/api/v1/auth/signup", json=payload)).status_code == 201
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert login.status_code == 200, login.text


def _csrf_headers(client: AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["csrf_token"]}


@pytest.mark.asyncio
async def test_saved_chat_persists_trip_and_versioned_follow_up(
    client: AsyncClient,
    valid_signup: dict[str, str],
    db_session: AsyncSession,
    fake_intent_model: FakeIntentModel,
) -> None:
    await _signup_and_login(client, valid_signup)
    conversation = await client.post(
        "/api/v1/conversations", json={}, headers=_csrf_headers(client)
    )
    conversation_id = conversation.json()["id"]
    first = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "Plan the example trip"},
        headers=_csrf_headers(client),
    )
    follow_up = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "budget kam karo"},
        headers=_csrf_headers(client),
    )
    assert first.status_code == 201, first.text
    assert follow_up.status_code == 201, follow_up.text
    assert follow_up.json()["trip"]["requirements"]["budget"] == "5000"
    assert fake_intent_model.calls[-1][1] is not None
    assert await db_session.scalar(select(func.count(Trip.id))) == 2
    assert await db_session.scalar(select(func.count(Itinerary.id))) == 2
    versions = list(
        (
            await db_session.scalars(select(Itinerary.version).order_by(Itinerary.version.asc()))
        ).all()
    )
    assert versions == [1, 2]


@pytest.mark.asyncio
async def test_get_trip_enforces_owner_and_expiry(
    client: AsyncClient,
    valid_signup: dict[str, str],
    db_session: AsyncSession,
) -> None:
    await _signup_and_login(client, valid_signup)
    conversation = await client.post(
        "/api/v1/conversations", json={}, headers=_csrf_headers(client)
    )
    conversation_id = conversation.json()["id"]
    turn = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "Plan this trip"},
        headers=_csrf_headers(client),
    )
    trip_id = turn.json()["trip"]["trip_id"]
    assert (await client.get(f"/api/v1/trips/{trip_id}")).status_code == 200

    client.cookies.clear()
    other = {
        "name": "Other User",
        "email": "trip-other@example.com",
        "password": "Other-strong-password-42",
        "confirm_password": "Other-strong-password-42",
    }
    await _signup_and_login(client, other)
    assert (await client.get(f"/api/v1/trips/{trip_id}")).status_code == 404

    await db_session.execute(
        update(Conversation)
        .where(Conversation.id == UUID(conversation_id))
        .values(expires_at=utc_now() - timedelta(seconds=1))
    )
    await db_session.commit()
    client.cookies.clear()
    await client.post(
        "/api/v1/auth/login",
        json={
            "email": valid_signup["email"],
            "password": valid_signup["password"],
        },
    )
    assert (await client.get(f"/api/v1/trips/{trip_id}")).status_code == 404


@pytest.mark.asyncio
async def test_missing_groq_key_returns_safe_error_and_logs_request_id(
    app: FastAPI,
    client: AsyncClient,
    settings: Settings,
    valid_signup: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    app.state.trip_planner = LangGraphTripPlanner(settings)
    await _signup_and_login(client, valid_signup)
    conversation = await client.post(
        "/api/v1/conversations", json={}, headers=_csrf_headers(client)
    )
    with caplog.at_level(logging.WARNING):
        response = await client.post(
            f"/api/v1/conversations/{conversation.json()['id']}/messages",
            json={"content": "Plan without a configured key"},
            headers=_csrf_headers(client),
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "trip_planning_unavailable"
    assert "Groq is not configured" not in response.text
    record = next(
        item for item in caplog.records if item.getMessage() == "Trip planning request failed"
    )
    assert record.request_id == response.json()["error"]["request_id"]  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_groq_400_is_logged_redacted_and_public_response_is_sanitized(
    app: FastAPI,
    client: AsyncClient,
    settings: Settings,
    valid_signup: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    api_key = "gsk_test_key_must_never_be_logged"
    user_prompt = "private prompt must never be logged"
    provider_error = FakeGroqBadRequest(
        {
            "error": {
                "type": "invalid_request_error",
                "message": (
                    "Bad request; api_key="
                    f"{api_key}; authorization=Bearer {api_key}; "
                    f"prompt={user_prompt}; email=private@example.com"
                ),
            }
        }
    )
    fake_client = FakeIntentCompletionClient(provider_error)
    _install_groq_intent_model(
        app,
        settings,
        fake_client,
        api_key=api_key,
    )
    await _signup_and_login(client, valid_signup)
    conversation = await client.post(
        "/api/v1/conversations", json={}, headers=_csrf_headers(client)
    )

    with caplog.at_level(logging.WARNING):
        response = await client.post(
            f"/api/v1/conversations/{conversation.json()['id']}/messages",
            json={"content": user_prompt},
            headers=_csrf_headers(client),
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "trip_planning_unavailable"
    assert api_key not in response.text
    assert user_prompt not in response.text
    record = next(
        item for item in caplog.records if item.getMessage() == "Trip planning request failed"
    )
    assert record.request_id == response.json()["error"]["request_id"]  # type: ignore[attr-defined]
    assert record.error_type == "FakeGroqBadRequest"  # type: ignore[attr-defined]
    assert record.http_status == 400  # type: ignore[attr-defined]
    logged_body = record.error_message  # type: ignore[attr-defined]
    assert "[REDACTED]" in logged_body
    assert api_key not in logged_body
    assert user_prompt not in logged_body
    assert "private@example.com" not in logged_body
    assert fake_client.calls == 1


@pytest.mark.asyncio
async def test_realistic_groq_json_normalizes_full_example_prompt(
    app: FastAPI,
    client: AsyncClient,
    settings: Settings,
    valid_signup: dict[str, str],
) -> None:
    prompt = (
        "30 Oct to 1 Nov, Hyderabad -> Pondicherry -> Rameshwaram, office by 2 Nov 10 AM, Rs 15,000"
    )
    fake_client = FakeIntentCompletionClient(
        {
            "origin": "Hyderabad",
            "destinations": ["Pondicherry", "Rameshwaram"],
            "start_date": "30 Oct",
            "end_date": "1 Nov",
            "travelers": None,
            "budget": 15000,
            "return_deadline": "2 Nov 10 AM",
            "preferences": None,
            "ambiguities": [
                "Number of travelers not specified",
                "Return deadline time zone assumed Asia/Kolkata",
            ],
        }
    )
    _install_groq_intent_model(
        app,
        settings,
        fake_client,
        api_key="gsk_example_test_key",
        current_date=date(2026, 10, 30),
    )
    await _signup_and_login(client, valid_signup)
    conversation = await client.post(
        "/api/v1/conversations", json={}, headers=_csrf_headers(client)
    )

    response = await client.post(
        f"/api/v1/conversations/{conversation.json()['id']}/messages",
        json={"content": prompt},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 201, response.text
    trip = response.json()["trip"]
    assert trip["status"] == "completed"
    assert trip["feasible"] is True
    assert trip["route_legs"]
    assert trip["itinerary_days"]
    assert trip["budget"]["categories"]
    assert "Travelers not specified; assuming 1." in trip["warnings"]
    assert "Return deadline timezone assumed Asia/Kolkata." in trip["warnings"]
    prices = [
        *(leg["price"] for leg in trip["route_legs"]),
        *(option["price"] for option in trip["transport_options"]),
        *(hotel["total_price"] for hotel in trip["hotels"]),
        *(place["entry_fee"] for place in trip["attractions"]),
        *trip["budget"]["categories"],
    ]
    assert prices
    assert all(price["price_type"] in {"unknown", "estimate"} for price in prices)
    assert all(price["price_type"] != "live_quote" for price in prices)
    requirements = trip["requirements"]
    assert requirements == {
        "origin": "Hyderabad",
        "destinations": ["Puducherry", "Rameswaram"],
        "start_date": "2026-10-30",
        "end_date": "2026-11-01",
        "travelers": 1,
        "budget": "15000",
        "return_deadline": "2026-11-02T10:00:00+05:30",
        "preferences": [],
        "ambiguities": [],
    }
    assert fake_client.calls == 1
    messages = fake_client.inputs[0]
    assert isinstance(messages, list)
    assert "Current date in Asia/Kolkata is 2026-10-30" in str(messages[0].content)


@pytest.mark.asyncio
@pytest.mark.parametrize("budget", [15000, "15000", "INR 15,000"])
async def test_budget_number_or_string_normalizes_to_decimal(
    settings: Settings,
    budget: object,
) -> None:
    fake_client = FakeIntentCompletionClient(
        {
            "origin": "Hyderabad",
            "destinations": ["Pondicherry"],
            "start_date": "2026-10-30",
            "end_date": "2026-11-01",
            "travelers": 1,
            "budget": budget,
            "return_deadline": "2026-11-02 10:00",
            "preferences": [],
            "ambiguities": [],
        }
    )
    groq_settings = _configured_groq_settings(settings, api_key="gsk_budget_test_key")
    model = GroqIntentModel(
        groq_settings,
        client=fake_client,
        today_provider=lambda: date(2026, 10, 30),
    )

    requirements = await model.extract_requirements(
        user_prompt="budget normalization test",
        previous_trip=None,
    )

    assert requirements.budget == Decimal("15000")
    assert fake_client.calls == 1


@pytest.mark.asyncio
async def test_null_critical_fields_return_specific_clarification_questions(
    app: FastAPI,
    client: AsyncClient,
    settings: Settings,
    valid_signup: dict[str, str],
) -> None:
    fake_client = FakeIntentCompletionClient(
        {
            "origin": None,
            "destinations": None,
            "start_date": None,
            "end_date": None,
            "travelers": None,
            "budget": None,
            "return_deadline": None,
            "preferences": None,
            "ambiguities": None,
        }
    )
    _install_groq_intent_model(
        app,
        settings,
        fake_client,
        api_key="gsk_clarification_test_key",
    )
    await _signup_and_login(client, valid_signup)
    conversation = await client.post(
        "/api/v1/conversations", json={}, headers=_csrf_headers(client)
    )

    response = await client.post(
        f"/api/v1/conversations/{conversation.json()['id']}/messages",
        json={"content": "Help me plan a trip"},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 201, response.text
    trip = response.json()["trip"]
    assert trip["status"] == "needs_clarification"
    assert trip["warnings"] == [
        "Which city are you starting from?",
        "Which destinations do you want to visit?",
        "What is your trip start date?",
        "What is your trip end date?",
    ]
    assert trip["route_legs"] == []
    assert fake_client.calls == 1


@pytest.mark.asyncio
async def test_invalid_date_returns_python_generated_clarification(
    app: FastAPI,
    client: AsyncClient,
    settings: Settings,
    valid_signup: dict[str, str],
) -> None:
    fake_client = FakeIntentCompletionClient(
        {
            "origin": "Hyderabad",
            "destinations": ["Pondicherry"],
            "start_date": "not a date",
            "end_date": "1 Nov",
            "travelers": 1,
            "budget": None,
            "return_deadline": None,
            "preferences": [],
            "ambiguities": ["The start date is unclear"],
        }
    )
    _install_groq_intent_model(
        app,
        settings,
        fake_client,
        api_key="gsk_invalid_date_test_key",
    )
    await _signup_and_login(client, valid_signup)
    conversation = await client.post(
        "/api/v1/conversations", json={}, headers=_csrf_headers(client)
    )

    response = await client.post(
        f"/api/v1/conversations/{conversation.json()['id']}/messages",
        json={"content": "Use an unclear start date"},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 201, response.text
    trip = response.json()["trip"]
    assert trip["status"] == "needs_clarification"
    assert trip["warnings"] == ["What is your trip start date?"]
    assert trip["route_legs"] == []
    assert fake_client.calls == 1


@pytest.mark.asyncio
async def test_validation_error_logs_only_location_and_type_without_retry(
    app: FastAPI,
    client: AsyncClient,
    settings: Settings,
    valid_signup: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    user_prompt = "private validation prompt"
    invalid_input = "private invalid traveler value"
    fake_client = FakeIntentCompletionClient(
        {
            "origin": "Hyderabad",
            "destinations": ["Pondicherry"],
            "start_date": "30 Oct",
            "end_date": "1 Nov",
            "travelers": invalid_input,
            "budget": "15000",
            "return_deadline": "2 Nov 10 AM",
            "preferences": [],
            "ambiguities": [],
        }
    )
    _install_groq_intent_model(
        app,
        settings,
        fake_client,
        api_key="gsk_validation_test_key",
    )
    await _signup_and_login(client, valid_signup)
    conversation = await client.post(
        "/api/v1/conversations", json={}, headers=_csrf_headers(client)
    )

    with caplog.at_level(logging.WARNING):
        response = await client.post(
            f"/api/v1/conversations/{conversation.json()['id']}/messages",
            json={"content": user_prompt},
            headers=_csrf_headers(client),
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "trip_planning_unavailable"
    assert user_prompt not in response.text
    assert fake_client.calls == 1
    record = next(
        item for item in caplog.records if item.getMessage() == "Trip planning request failed"
    )
    assert record.error_type == "ValidationError"  # type: ignore[attr-defined]
    assert record.http_status is None  # type: ignore[attr-defined]
    assert record.validation_errors == [  # type: ignore[attr-defined]
        {"loc": ["travelers"], "type": "int_parsing"}
    ]
    assert invalid_input not in str(record.validation_errors)  # type: ignore[attr-defined]
    assert user_prompt not in record.error_message  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_malformed_json_retries_once_and_stays_sanitized(
    app: FastAPI,
    client: AsyncClient,
    settings: Settings,
    valid_signup: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    user_prompt = "malformed JSON private prompt"
    fake_client = FakeIntentCompletionClient("{not valid JSON", "{still not valid JSON")
    _install_groq_intent_model(
        app,
        settings,
        fake_client,
        api_key="gsk_malformed_test_key",
    )
    await _signup_and_login(client, valid_signup)
    conversation = await client.post(
        "/api/v1/conversations", json={}, headers=_csrf_headers(client)
    )

    with caplog.at_level(logging.WARNING):
        response = await client.post(
            f"/api/v1/conversations/{conversation.json()['id']}/messages",
            json={"content": user_prompt},
            headers=_csrf_headers(client),
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "trip_planning_unavailable"
    assert user_prompt not in response.text
    assert fake_client.calls == 2
    record = next(
        item for item in caplog.records if item.getMessage() == "Trip planning request failed"
    )
    assert record.error_type == "JSONDecodeError"  # type: ignore[attr-defined]
    assert record.validation_errors == []  # type: ignore[attr-defined]
    assert record.error_message == "Model output was not valid JSON"  # type: ignore[attr-defined]
    assert user_prompt not in record.error_message  # type: ignore[attr-defined]
