from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import LangGraphTripPlanner
from app.core.config import Settings
from app.integrations.base import ProviderFailure
from app.integrations.serpapi_flights import FlightProviderResult
from app.models.price_history import PriceHistory
from app.repositories.price_history_repository import (
    PriceHistoryRepository,
    PriceHistoryWrite,
)
from app.schemas.common import PriceQuote
from app.schemas.trip import TripRequirements, TripResponse
from app.services.price_engine import QUOTA_WARNING, PriceEngine, PriceQuery
from app.utils.datetime_utils import INDIA_TIME_ZONE

NOW = datetime(2026, 11, 3, 6, 0, tzinfo=INDIA_TIME_ZONE)


class FakeFlights:
    def __init__(self, result: FlightProviderResult | ProviderFailure) -> None:
        self.result = result
        self.calls = 0

    async def search_one_way(self, **_kwargs: object) -> FlightProviderResult:
        self.calls += 1
        if isinstance(self.result, ProviderFailure):
            raise self.result
        return self.result


class DelhiIntentModel:
    async def extract_requirements(
        self, *, user_prompt: str, previous_trip: TripResponse | None
    ) -> TripRequirements:
        del user_prompt, previous_trip
        return TripRequirements(
            origin="Hyderabad",
            destinations=["Delhi"],
            start_date=date(2026, 11, 10),
            end_date=date(2026, 11, 12),
            travelers=1,
            return_to_origin=False,
        )


def _settings(settings: Settings, **updates: object) -> Settings:
    return settings.model_copy(
        update={
            "serpapi_enabled": True,
            "google_serp_api_key": SecretStr("fake-serp-key"),
            "serpapi_monthly_budget": 250,
            "serpapi_max_searches_per_trip": 3,
            "price_history_enabled": True,
            **updates,
        }
    )


def _query(**updates: object) -> PriceQuery:
    values = {
        "mode": "flight",
        "origin_code": "HYD",
        "destination_code": "DEL",
        "travel_date": date(2026, 11, 10),
        "cabin_or_class": "economy",
        "passengers": 1,
        "nights": None,
        "price_unit": "one adult one-way",
    }
    values.update(updates)
    return PriceQuery(**values)  # type: ignore[arg-type]


def _formula() -> PriceQuote:
    return PriceQuote(
        amount_min=Decimal("5000"),
        amount_max=Decimal("9000"),
        price_type="estimate",
        source="distance_formula",
        fetched_at=NOW,
        status="formula_estimate",
        provider="distance_formula",
        observed_at=NOW,
        price_unit="one adult one-way",
        note="rough formula estimate",
    )


def _engine(
    app: FastAPI,
    settings: Settings,
    flights: FakeFlights | None,
) -> PriceEngine:
    return PriceEngine(
        settings,
        app.state.redis,
        app.state.db_session_factory,
        flights=flights,  # type: ignore[arg-type]
        now_provider=lambda: NOW,
    )


async def _insert_history(
    db: AsyncSession,
    query: PriceQuery,
    *,
    price: str,
    observed_at: datetime,
    is_demo: bool = False,
    bucket: str | None = None,
) -> None:
    await PriceHistoryRepository(db).add(
        PriceHistoryWrite(
            context=query.context(),
            mode=query.mode,
            origin_code=query.origin_code,
            destination_code=query.destination_code,
            travel_date=query.travel_date,
            observed_at=observed_at,
            booking_bucket=bucket or query.booking_bucket(NOW),
            price=Decimal(price),
            currency="INR",
            provider="SerpApi Google Flights",
            price_unit=query.price_unit,
            cabin_or_class=query.cabin_or_class,
            passengers=query.passengers,
            nights=query.nights,
            is_demo=is_demo,
            expires_at=NOW + timedelta(days=180),
        )
    )
    await db.commit()


@pytest.mark.asyncio
async def test_live_success_returns_live_status_and_saves_anonymous_history(
    app: FastAPI,
    client: AsyncClient,
    settings: Settings,
    db_session: AsyncSession,
) -> None:
    del client
    provider = FakeFlights(FlightProviderResult(amount=Decimal("6200"), observed_at=NOW))
    engine = _engine(app, _settings(settings), provider)

    resolved, _ = await engine._resolve_flight(
        trip_id=uuid4(), query=_query(), formula=_formula()
    )

    assert resolved.quote.status == "live_search_result"
    assert resolved.quote.price_type == "live_quote"
    assert resolved.quote.bookable is False
    assert "search result, not a confirmed booking" in (resolved.quote.note or "")
    row = await db_session.scalar(select(PriceHistory))
    assert row is not None
    assert row.price == Decimal("6200.00")
    assert not hasattr(row, "user_id")
    assert not hasattr(row, "trip_id")
    assert not hasattr(row, "prompt")


@pytest.mark.asyncio
@pytest.mark.parametrize(("count", "expected"), [(1, "previous"), (2, "previous"), (3, "estimated")])
async def test_provider_failure_uses_previous_or_median_history(
    app: FastAPI,
    client: AsyncClient,
    settings: Settings,
    db_session: AsyncSession,
    count: int,
    expected: str,
) -> None:
    del client
    query = _query()
    for index in range(count):
        await _insert_history(
            db_session,
            query,
            price=str(4000 + index * 1000),
            observed_at=NOW - timedelta(days=index + 1),
        )
    provider = FakeFlights(ProviderFailure("timeout", "timeout"))
    engine = _engine(app, _settings(settings), provider)

    resolved, _ = await engine._resolve_flight(
        trip_id=uuid4(), query=query, formula=_formula()
    )

    assert resolved.quote.status == expected
    if expected == "estimated":
        assert resolved.quote.amount == Decimal("5000.00")
        assert resolved.quote.amount_min == Decimal("4000.00")
        assert resolved.quote.amount_max == Decimal("6000.00")
        assert resolved.quote.sample_count == 3
    else:
        assert resolved.quote.amount == Decimal("4000.00")


@pytest.mark.asyncio
async def test_no_history_uses_formula_and_disabled_provider_does_not_crash(
    app: FastAPI,
    client: AsyncClient,
    settings: Settings,
) -> None:
    del client
    disabled = _settings(settings, serpapi_enabled=False, google_serp_api_key=None)
    resolved, _ = await _engine(app, disabled, None)._resolve_flight(
        trip_id=uuid4(), query=_query(), formula=_formula()
    )
    assert resolved.quote.status == "formula_estimate"
    assert resolved.quote.amount_min == 5000


@pytest.mark.asyncio
async def test_valid_empty_result_is_unavailable_and_never_uses_history_or_formula(
    app: FastAPI,
    client: AsyncClient,
    settings: Settings,
    db_session: AsyncSession,
) -> None:
    del client
    query = _query()
    await _insert_history(
        db_session,
        query,
        price="4500",
        observed_at=NOW - timedelta(days=1),
    )
    provider = FakeFlights(FlightProviderResult(amount=None, observed_at=NOW))
    resolved, _ = await _engine(app, _settings(settings), provider)._resolve_flight(
        trip_id=uuid4(), query=query, formula=_formula()
    )
    assert resolved.quote.status == "unavailable"
    assert resolved.quote.amount is None
    assert resolved.quote.note == "No matching service for the searched date"
    assert "price_history" not in resolved.tried


@pytest.mark.asyncio
async def test_context_and_bucket_boundaries_exclude_mismatched_history(
    app: FastAPI,
    client: AsyncClient,
    settings: Settings,
    db_session: AsyncSession,
) -> None:
    del client
    economy = _query()
    business = _query(cabin_or_class="business")
    await _insert_history(
        db_session,
        business,
        price="9000",
        observed_at=NOW - timedelta(days=1),
    )
    await _insert_history(
        db_session,
        economy,
        price="4000",
        observed_at=NOW - timedelta(days=1),
        bucket="31_plus",
    )
    resolved, _ = await _engine(
        app,
        _settings(settings),
        FakeFlights(ProviderFailure("timeout", "timeout")),
    )._resolve_flight(trip_id=uuid4(), query=economy, formula=_formula())
    assert resolved.quote.status == "formula_estimate"


@pytest.mark.asyncio
async def test_old_and_demo_rows_are_ignored_unless_demo_flag_is_enabled(
    app: FastAPI,
    client: AsyncClient,
    settings: Settings,
    db_session: AsyncSession,
) -> None:
    del client
    query = _query()
    await _insert_history(
        db_session,
        query,
        price="3000",
        observed_at=NOW - timedelta(days=91),
    )
    await _insert_history(
        db_session,
        query,
        price="3500",
        observed_at=NOW - timedelta(days=1),
        is_demo=True,
    )
    provider = FakeFlights(ProviderFailure("timeout", "timeout"))
    resolved, _ = await _engine(app, _settings(settings), provider)._resolve_flight(
        trip_id=uuid4(), query=query, formula=_formula()
    )
    assert resolved.quote.status == "formula_estimate"

    await app.state.redis.flushdb()
    resolved_demo, _ = await _engine(
        app,
        _settings(settings, allow_demo_price_data=True),
        provider,
    )._resolve_flight(trip_id=uuid4(), query=query, formula=_formula())
    assert resolved_demo.quote.status == "previous"
    assert resolved_demo.quote.amount == 3500


@pytest.mark.asyncio
async def test_quota_exhaustion_falls_back_with_warning_and_cache_avoids_second_call(
    app: FastAPI,
    client: AsyncClient,
    settings: Settings,
) -> None:
    del client
    provider = FakeFlights(FlightProviderResult(amount=Decimal("6200"), observed_at=NOW))
    configured = _settings(settings, serpapi_monthly_budget=1)
    engine = _engine(app, configured, provider)
    query = _query()
    first, _ = await engine._resolve_flight(
        trip_id=uuid4(), query=query, formula=_formula()
    )
    second, _ = await engine._resolve_flight(
        trip_id=uuid4(), query=query, formula=_formula()
    )
    assert first.quote.status == "live_search_result"
    assert second.quote.status == "previous"
    assert provider.calls == 1

    await app.state.redis.flushdb()
    await app.state.redis.set("price:serpapi:month:2026-11", "1")
    quota_provider = FakeFlights(FlightProviderResult(amount=Decimal("7000"), observed_at=NOW))
    quota_result, _ = await _engine(app, configured, quota_provider)._resolve_flight(
        trip_id=uuid4(), query=_query(cabin_or_class="premium_economy"), formula=_formula()
    )
    assert quota_result.quote.status == "formula_estimate"
    assert quota_result.warning == QUOTA_WARNING
    assert quota_provider.calls == 0


@pytest.mark.asyncio
async def test_non_inr_history_is_rejected(db_session: AsyncSession) -> None:
    query = _query()
    with pytest.raises(ValueError, match="INR only"):
        await PriceHistoryRepository(db_session).add(
            PriceHistoryWrite(
                context=query.context(),
                mode=query.mode,
                origin_code=query.origin_code,
                destination_code=query.destination_code,
                travel_date=query.travel_date,
                observed_at=NOW,
                booking_bucket=query.booking_bucket(NOW),
                price=Decimal("100"),
                currency="USD",
                provider="fake",
                price_unit=query.price_unit,
                cabin_or_class=query.cabin_or_class,
                passengers=1,
                nights=None,
                is_demo=False,
                expires_at=NOW + timedelta(days=1),
            )
        )


@pytest.mark.asyncio
async def test_null_price_never_becomes_zero(
    app: FastAPI,
    client: AsyncClient,
    settings: Settings,
) -> None:
    del client
    unavailable_formula = _formula().model_copy(
        update={
            "amount_min": None,
            "amount_max": None,
            "price_type": "unknown",
            "status": "unavailable",
        }
    )
    resolved, _ = await _engine(app, _settings(settings), None)._resolve_flight(
        trip_id=uuid4(), query=_query(), formula=unavailable_formula
    )
    assert resolved.quote.status == "unavailable"
    assert resolved.quote.amount is None
    assert resolved.quote.amount_min is None
    assert resolved.quote.amount_max is None
    assert await db_session_count(app.state.db_session_factory) == 0


@pytest.mark.asyncio
async def test_temporary_graph_uses_live_engine_without_postgres_history(
    app: FastAPI,
    client: AsyncClient,
    settings: Settings,
) -> None:
    del client
    provider = FakeFlights(FlightProviderResult(amount=Decimal("6200"), observed_at=NOW))
    configured = _settings(settings)
    planner = LangGraphTripPlanner(
        configured,
        intent_model=DelhiIntentModel(),
        now_provider=lambda: NOW,
        price_engine=_engine(app, configured, provider),
    )

    response = await planner.run(
        conversation_id=None,
        user_prompt="mujhe hyderabad se delhi jana hai 10/11/2026",
        previous_trip=None,
        chat_mode="temporary",
    )

    assert provider.calls == 1
    assert any(
        option.mode == "flight" and option.price.status == "live_search_result"
        for option in response.transport_options
    )
    assert await db_session_count(app.state.db_session_factory) == 0


def test_hotel_history_context_requires_the_same_date_window() -> None:
    first = _query(
        mode="hotel",
        origin_code=None,
        destination_code="delhi",
        travel_date=date(2026, 11, 10),
        cabin_or_class="budget",
        nights=2,
        price_unit="one room, full stay",
    )
    next_day = _query(
        mode="hotel",
        origin_code=None,
        destination_code="delhi",
        travel_date=date(2026, 11, 11),
        cabin_or_class="budget",
        nights=2,
        price_unit="one room, full stay",
    )

    assert first.context() != next_day.context()


async def db_session_count(session_factory: object) -> int:
    async with session_factory() as session:  # type: ignore[operator]
        return int(await session.scalar(select(func.count(PriceHistory.id))) or 0)
