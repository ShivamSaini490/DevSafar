import logging
from datetime import date, datetime, timedelta
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
from app.utils.datetime_utils import INDIA_TIME_ZONE


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


def _complete_intent_payload(
    *,
    return_deadline: str,
    ambiguities: list[str] | None = None,
) -> dict[str, object]:
    return {
        "origin": "Hyderabad",
        "destinations": ["Vijayawada"],
        "start_date": "31 Oct",
        "end_date": "4 Nov",
        "travelers": 1,
        "budget": "INR 20000",
        "return_deadline": return_deadline,
        "preferences": [],
        "ambiguities": ambiguities or [],
    }


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
        now_provider=lambda: datetime(2026, 10, 30, 5, 0, tzinfo=INDIA_TIME_ZONE),
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
async def test_hinglish_morning_return_time_overrides_provider_midnight(
    settings: Settings,
) -> None:
    fake_client = FakeIntentCompletionClient(
        _complete_intent_payload(
            return_deadline="2026-11-05T00:00:00",
            ambiguities=[
                "Exact return time not specified",
                "Currency assumed INR",
                "Timezone assumed Asia/Kolkata",
            ],
        )
    )
    groq_settings = _configured_groq_settings(settings, api_key="gsk_hinglish_test_key")
    model = GroqIntentModel(
        groq_settings,
        client=fake_client,
        today_provider=lambda: date(2026, 10, 30),
    )

    requirements = await model.extract_requirements(
        user_prompt=(
            "31 Oct se 4 Nov Hyderabad se Vijayawada trip, "
            "5 Nov subah 10 baje tak wapas, budget INR 20000"
        ),
        previous_trip=None,
    )

    assert requirements.return_deadline == datetime(
        2026, 11, 5, 10, 0, tzinfo=INDIA_TIME_ZONE
    )
    assert requirements.ambiguities == []
    system_message = str(fake_client.inputs[0][0].content)  # type: ignore[index,union-attr]
    for example in ("subah 10 baje", "dopahar 2 baje", "shaam 7 baje", "raat 10 baje"):
        assert example in system_message


@pytest.mark.asyncio
async def test_return_date_without_time_defaults_to_end_of_day_and_warns(
    settings: Settings,
) -> None:
    fake_client = FakeIntentCompletionClient(
        _complete_intent_payload(
            return_deadline="2026-11-05T00:00:00",
            ambiguities=["Exact return time not specified", "Currency assumed INR"],
        )
    )
    groq_settings = _configured_groq_settings(settings, api_key="gsk_no_time_test_key")
    model = GroqIntentModel(
        groq_settings,
        client=fake_client,
        today_provider=lambda: date(2026, 10, 30),
    )
    response = await LangGraphTripPlanner(
        groq_settings,
        intent_model=model,
        now_provider=lambda: datetime(2026, 10, 30, 5, 0, tzinfo=INDIA_TIME_ZONE),
    ).run(
        conversation_id=None,
        user_prompt="31 Oct se 4 Nov Hyderabad se Vijayawada, 5 Nov tak wapas",
        previous_trip=None,
        chat_mode="temporary",
    )

    assert response.requirements.return_deadline == datetime(
        2026, 11, 5, 23, 59, tzinfo=INDIA_TIME_ZONE
    )
    assert "Return time not specified; assuming 23:59 Asia/Kolkata." in response.assumptions
    assert not any(
        noise in warning.casefold()
        for warning in response.warnings
        for noise in ("currency assumed", "timezone assumed", "time zone assumed")
    )


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
    assert trip["feasible"] is None
    assert len(trip["route_legs"]) == 3
    assert [(leg["origin"], leg["destination"]) for leg in trip["route_legs"]] == [
        ("Hyderabad", "Puducherry"),
        ("Puducherry", "Rameswaram"),
        ("Rameswaram", "Hyderabad"),
    ]
    assert all(leg["mode"] for leg in trip["route_legs"])
    assert all(leg["duration_minutes"] for leg in trip["route_legs"])
    assert all(leg["departure_at"] for leg in trip["route_legs"])
    assert all(leg["arrival_at"] for leg in trip["route_legs"])
    assert all(
        current["departure_at"] >= previous["arrival_at"]
        for previous, current in zip(trip["route_legs"], trip["route_legs"][1:], strict=False)
    )
    assert trip["itinerary_days"]
    assert trip["budget"]["categories"]
    assert Decimal(trip["budget"]["known_subtotal"]) > 0
    assert "Transport" in trip["budget"]["unknown_categories"]
    assert "Attractions" in trip["budget"]["unknown_categories"]
    assert trip["budget"]["omitted_categories"] == ["Transport", "Attractions"]
    assert "Travelers not specified; assuming 1." in trip["assumptions"]
    assert not any("timezone" in warning.casefold() for warning in trip["warnings"])
    assert (
        "Feasibility based on rough estimates; verify timetables." in trip["warnings"]
    )

    arrivals = {leg["destination"]: leg["arrival_at"] for leg in trip["route_legs"]}
    for day in trip["itinerary_days"]:
        for activity in day["activities"]:
            if activity["location"] in arrivals and activity["starts_at"] is not None:
                assert activity["starts_at"] >= arrivals[activity["location"]]
    return_day = trip["itinerary_days"][-1]
    assert return_day["date"] == trip["requirements"]["end_date"]
    assert return_day["destination"] == "Hyderabad"
    assert any(activity["title"] == "Arrive in Hyderabad" for activity in return_day["activities"])

    for hotel in trip["hotels"]:
        assert hotel["destination"] != "Hyderabad"
        assert hotel["tier"] in {"budget", "standard", "comfort"}
        assert hotel["total_price"]["source"] == "tier_assumption"
        assert hotel["total_price"]["amount_min"] <= hotel["total_price"]["amount_max"]
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
        "return_to_origin": True,
        "preferences": [],
        "ambiguities": [],
    }
    assert fake_client.calls == 1
    messages = fake_client.inputs[0]
    assert isinstance(messages, list)
    assert "Current date in Asia/Kolkata is 2026-10-30" in str(messages[0].content)


@pytest.mark.asyncio
async def test_hyderabad_delhi_without_budget_or_return_has_complete_ranges(
    app: FastAPI,
    client: AsyncClient,
    settings: Settings,
    valid_signup: dict[str, str],
) -> None:
    prompt = "mujhe hyderabad se delhi jana hai 03/11/2026"
    fake_client = FakeIntentCompletionClient(
        {
            "origin": "Hyderabad",
            "destinations": ["Delhi"],
            "start_date": "03/11/2026",
            "end_date": None,
            "travelers": 1,
            "budget": None,
            "return_deadline": None,
            "return_to_origin": False,
            "preferences": [],
            "ambiguities": [],
        }
    )
    _install_groq_intent_model(
        app,
        settings,
        fake_client,
        api_key="fake-delhi-regression-key",
        current_date=date(2026, 11, 3),
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
    assert trip["requirements"]["end_date"] == "2026-11-05"
    assert trip["mode_comparison"]
    flight = next(item for item in trip["mode_comparison"] if item["mode"] == "flight")
    assert flight["duration_minutes_min"] is not None
    assert flight["duration_minutes_max"] is not None
    assert flight["transport_price"]["amount"] is not None or (
        flight["transport_price"]["amount_min"] is not None
        and flight["transport_price"]["amount_max"] is not None
    )
    route_leg = trip["route_legs"][0]
    assert route_leg["mode"] == "flight"
    assert route_leg["duration_minutes_min"] is not None
    assert route_leg["duration_minutes_max"] is not None
    assert route_leg["price"]["amount"] is not None or (
        route_leg["price"]["amount_min"] is not None
        and route_leg["price"]["amount_max"] is not None
    )
    for hotel in trip["hotels"]:
        assert hotel["total_price"]["amount"] is not None or (
            hotel["total_price"]["amount_min"] is not None
            and hotel["total_price"]["amount_max"] is not None
        )
    categories = {item["name"]: item for item in trip["budget"]["categories"]}
    for name in ("Transport", "Hotels", "Food", "Local transport"):
        assert categories[name]["amount"] is not None or (
            categories[name]["amount_min"] is not None
            and categories[name]["amount_max"] is not None
        )
    assert Decimal(trip["budget"]["known_subtotal"]) > 0
    assert trip["budget"]["estimated_total_min"] is not None
    assert trip["budget"]["estimated_total_max"] is not None
    assert trip["budget"]["omitted_categories"] == ["Attractions"]
    assert fake_client.calls == 1


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
    ]
    assert len(trip["assumptions"]) >= 4
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
    assert trip["warnings"] == ["What valid future start date should I use?"]
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
