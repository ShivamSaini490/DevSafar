from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import NoReturn

import httpx
import pytest
from pydantic import ValidationError

from app.agents.graph import LangGraphTripPlanner
from app.core.config import Settings
from app.core.security import utc_now
from app.db.session import create_redis_client
from app.integrations.base import ProviderBundle
from app.integrations.maps_provider import OsmMapsProvider
from app.schemas.common import PriceQuote
from app.schemas.transport import RouteLeg
from app.schemas.trip import TripRequirements, TripResponse
from app.services.route_service import ordered_route_stops
from app.utils.datetime_utils import INDIA_TIME_ZONE
from app.utils.url_validator import validate_external_base_url


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class StaticIntentModel:
    def __init__(self, requirements: TripRequirements) -> None:
        self.requirements = requirements

    async def extract_requirements(
        self,
        *,
        user_prompt: str,
        previous_trip: TripResponse | None,
    ) -> TripRequirements:
        del user_prompt, previous_trip
        return self.requirements.model_copy(deep=True)


class StaticRoadProvider:
    def __init__(self, *, distance_km: Decimal, duration_minutes: int) -> None:
        self.distance_km = distance_km
        self.duration_minutes = duration_minutes

    async def route_legs(self, requirements: TripRequirements) -> list[RouteLeg]:
        stops = ordered_route_stops(requirements)
        return [
            RouteLeg(
                origin=origin,
                destination=destination,
                mode="road",
                distance_km=self.distance_km,
                duration_minutes=self.duration_minutes,
                duration_source="osrm",
                price=PriceQuote(
                    amount=self.distance_km * Decimal("12.00"),
                    price_type="estimate",
                    source="fuel_formula",
                    fetched_at=utc_now(),
                ),
            )
            for origin, destination in zip(stops, stops[1:], strict=False)
        ]


def _geocode_response() -> httpx.Response:
    return httpx.Response(200, json=[{"lat": "17.385", "lon": "78.4867"}])


@pytest.mark.asyncio
async def test_geocode_cache_hit_avoids_second_external_call(settings: Settings) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.params["q"] == "Hyderabad"
        assert request.url.params["countrycodes"] == "in"
        return _geocode_response()

    redis = create_redis_client(settings)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OsmMapsProvider(settings, redis, client=client)
        first = await provider.geocode("Hyderabad")
        second = await provider.geocode("Hyderabad")
    assert first == second
    assert calls == 1
    cache_keys = await redis.keys("devsafar:maps:geocode:v1:*")
    assert len(cache_keys) == 1
    assert await redis.ttl(cache_keys[0]) > 86_400
    await redis.aclose()


@pytest.mark.asyncio
async def test_nominatim_requests_are_rate_limited_to_one_per_second(settings: Settings) -> None:
    clock = FakeClock()

    def handler(_request: httpx.Request) -> httpx.Response:
        return _geocode_response()

    redis = create_redis_client(settings)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OsmMapsProvider(
            settings,
            redis,
            client=client,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )
        assert await provider.geocode("Hyderabad") is not None
        assert await provider.geocode("Puducherry") is not None
    assert clock.sleeps == [1.0]
    await redis.aclose()


@pytest.mark.asyncio
async def test_osrm_failure_returns_unknown_instead_of_fake_numbers(settings: Settings) -> None:
    clock = FakeClock()
    osrm_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal osrm_calls
        if "/search" in request.url.path:
            return _geocode_response()
        osrm_calls += 1
        return httpx.Response(503, json={"message": "temporarily unavailable"})

    redis = create_redis_client(settings)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OsmMapsProvider(
            settings,
            redis,
            client=client,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )
        legs = await provider.route_legs(
            TripRequirements(
                origin="Hyderabad",
                destinations=["Puducherry"],
                start_date=date(2026, 10, 30),
                end_date=date(2026, 10, 31),
                return_deadline=datetime(2026, 11, 1, 12, tzinfo=INDIA_TIME_ZONE),
            )
        )
    assert osrm_calls == 3
    assert len(legs) == 2
    assert all(leg.duration_minutes is None for leg in legs)
    assert all(leg.distance_km is None for leg in legs)
    assert all(leg.price.amount is None for leg in legs)
    assert all(leg.price.price_type == "unknown" for leg in legs)
    await redis.aclose()


@pytest.mark.parametrize(
    "url",
    [
        "http://router.project-osrm.org",
        "https://127.0.0.1",
        "https://169.254.169.254",
        "https://localhost",
        "https://evil.example",
        "https://user:password@router.project-osrm.org",
    ],
)
def test_url_validation_rejects_unsafe_base_urls(url: str) -> None:
    with pytest.raises(ValueError):
        validate_external_base_url(
            url,
            allowed_hosts=frozenset(
                {"router.project-osrm.org", "nominatim.openstreetmap.org"}
            ),
        )


def test_settings_reject_bad_maps_base_url(settings: Settings) -> None:
    values = settings.model_dump()
    values["osrm_base_url"] = "https://evil.example"
    with pytest.raises(ValidationError):
        Settings.model_validate(values)


@pytest.mark.asyncio
async def test_osrm_legs_have_distance_duration_and_fuel_estimate(settings: Settings) -> None:
    clock = FakeClock()

    def handler(request: httpx.Request) -> httpx.Response:
        if "/search" in request.url.path:
            return _geocode_response()
        return httpx.Response(
            200,
            json={
                "code": "Ok",
                "routes": [
                    {
                        "legs": [
                            {"distance": 100_000, "duration": 7_200},
                            {"distance": 100_000, "duration": 7_200},
                        ]
                    }
                ],
            },
        )

    redis = create_redis_client(settings)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OsmMapsProvider(
            settings,
            redis,
            client=client,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )
        legs = await provider.route_legs(
            TripRequirements(
                origin="Hyderabad",
                destinations=["Puducherry"],
                start_date=date(2026, 10, 30),
                end_date=date(2026, 10, 30),
                return_deadline=datetime(2026, 10, 31, 18, tzinfo=INDIA_TIME_ZONE),
            )
        )
    assert len(legs) == 2
    assert all(leg.mode == "road" for leg in legs)
    assert all(leg.duration_source == "osrm" for leg in legs)
    assert all(leg.distance_km == Decimal("100.000") for leg in legs)
    assert all(leg.price.amount == Decimal("1200.00") for leg in legs)
    assert all(leg.price.price_type == "estimate" for leg in legs)
    assert all(leg.price.source == "fuel_formula" for leg in legs)
    await redis.aclose()


async def _run_road_plan(
    settings: Settings,
    *,
    distance_km: Decimal,
    duration_minutes: int,
    deadline: datetime,
    now: datetime | None = None,
    min_stay_hours: int = 6,
    destination: str = "Puducherry",
) -> TripResponse:
    osm_settings = settings.model_copy(
        update={
            "maps_provider": "osm",
            "min_stay_hours_per_destination": min_stay_hours,
        }
    )
    requirements = TripRequirements(
        origin="Hyderabad",
        destinations=[destination],
        start_date=date(2026, 10, 30),
        end_date=date(2026, 10, 30),
        budget=Decimal("1000000"),
        return_deadline=deadline,
    )
    road_provider = StaticRoadProvider(
        distance_km=distance_km,
        duration_minutes=duration_minutes,
    )

    def provider_factory(fetched_at: datetime) -> ProviderBundle:
        return ProviderBundle.stubs(fetched_at).with_maps(
            road_provider,
            source_name="osrm",
        )

    planner = LangGraphTripPlanner(
        osm_settings,
        intent_model=StaticIntentModel(requirements),
        provider_factory=provider_factory,
        now_provider=lambda: now
        or datetime(2026, 10, 30, 5, 0, tzinfo=INDIA_TIME_ZONE),
    )
    return await planner.run(
        conversation_id=None,
        user_prompt="city-only fake provider test",
        previous_trip=None,
        chat_mode="saved",
    )


def _assert_no_positive_duration_overlaps(response: TripResponse) -> None:
    activities = sorted(
        (
            activity
            for day in response.itinerary_days
            for activity in day.activities
            if activity.starts_at is not None and activity.ends_at is not None
        ),
        key=lambda activity: activity.starts_at,  # type: ignore[arg-type,return-value]
    )
    for previous, current in zip(activities, activities[1:], strict=False):
        assert previous.ends_at is not None
        assert current.starts_at is not None
        if previous.ends_at > previous.starts_at:  # type: ignore[operator]
            assert previous.ends_at <= current.starts_at


@pytest.mark.asyncio
async def test_vijayawada_round_trip_stays_six_hours_and_returns_same_day(
    settings: Settings,
) -> None:
    response = await _run_road_plan(
        settings,
        distance_km=Decimal("268"),
        duration_minutes=216,
        deadline=datetime(2026, 10, 30, 21, tzinfo=INDIA_TIME_ZONE),
        destination="Vijayawada",
    )

    assert response.feasible is True
    assert all(leg.overnight_stops == 0 for leg in response.route_legs)
    assert not any(hotel.destination == "en route" for hotel in response.hotels)
    assert response.route_legs[-1].arrival_at == datetime(
        2026, 10, 30, 19, 12, tzinfo=INDIA_TIME_ZONE
    )
    stay = next(
        activity
        for day in response.itinerary_days
        for activity in day.activities
        if activity.title == "Stay in Vijayawada"
    )
    assert stay.ends_at is not None and stay.starts_at is not None
    assert stay.ends_at - stay.starts_at == timedelta(hours=6)
    _assert_no_positive_duration_overlaps(response)


@pytest.mark.asyncio
async def test_1100_km_leg_splits_within_daily_and_clock_limits(settings: Settings) -> None:
    response = await _run_road_plan(
        settings,
        distance_km=Decimal("1100"),
        duration_minutes=900,
        deadline=datetime(2026, 11, 5, 21, tzinfo=INDIA_TIME_ZONE),
    )

    assert response.route_legs[0].overnight_stops >= 1
    assert len(response.route_legs[0].driving_segments) >= 2
    for leg in response.route_legs:
        driven_by_date: dict[date, int] = {}
        for segment in leg.driving_segments:
            minutes = int((segment.ends_at - segment.starts_at).total_seconds() // 60)
            driven_by_date[segment.starts_at.date()] = (
                driven_by_date.get(segment.starts_at.date(), 0) + minutes
            )
            latest = datetime.combine(
                segment.ends_at.date(),
                datetime.min.time(),
                tzinfo=INDIA_TIME_ZONE,
            ).replace(hour=settings.driving_latest_arrival_hour)
            assert segment.ends_at <= latest
        assert all(
            minutes <= settings.max_driving_hours_per_day * 60
            for minutes in driven_by_date.values()
        )
    _assert_no_positive_duration_overlaps(response)


@pytest.mark.asyncio
async def test_long_road_route_uses_multi_day_schedule_and_misses_deadline(
    settings: Settings,
) -> None:
    response = await _run_road_plan(
        settings,
        distance_km=Decimal("1000"),
        duration_minutes=960,
        deadline=datetime(2026, 10, 31, 10, tzinfo=INDIA_TIME_ZONE),
    )
    assert response.feasible is False
    assert response.status == "completed"
    assert len(response.route_legs) == 2
    assert sum(leg.overnight_stops for leg in response.route_legs) >= 2
    assert response.route_legs[-1].arrival_at is not None
    assert response.route_legs[-1].arrival_at > response.requirements.return_deadline
    assert any("misses the required return deadline" in warning for warning in response.warnings)
    assert any("overnight rest stop" in warning for warning in response.warnings)
    assert response.warnings[-4:] == [
        "Alternative 1: Compare train/bus/flight options (not integrated yet; links to official "
        "search pages are coming).",
        "Alternative 2: Extend the trip dates or return deadline.",
        "Alternative 3: Drop a destination.",
        "Alternative 4: Increase the budget.",
    ]
    assert (
        "Based on road travel estimates only; trains, buses and flights are not compared yet."
        in response.warnings
    )
    assert (
        "Road cost assumes a private car at INR 12.00 per km; adjust FUEL_COST_PER_KM."
        in response.warnings
    )
    assert (
        "OSRM durations exclude traffic, so real travel time may be longer."
        in response.warnings
    )
    assert len(response.transport_options) == len(response.route_legs)
    for option, leg in zip(response.transport_options, response.route_legs, strict=True):
        assert option.origin == leg.origin
        assert option.destination == leg.destination
        assert option.provider == "osrm+fuel_formula"
        assert option.distance_km == leg.distance_km
        assert option.duration_minutes == leg.duration_minutes
        assert option.price == leg.price
        assert option.price.price_type == "estimate"

    rest_stays = [
        hotel
        for hotel in response.hotels
        if hotel.name.startswith("Overnight rest stop between")
    ]
    assert rest_stays
    assert all(hotel.destination == "en route" for hotel in rest_stays)
    assert all(hotel.destination != response.requirements.origin for hotel in response.hotels)
    assert all(hotel.check_out > hotel.check_in for hotel in response.hotels)
    assert all(hotel.total_price.price_type == "estimate" for hotel in rest_stays)
    assert all(hotel.total_price.source == "stub_overnight_rest_estimate" for hotel in rest_stays)

    assert all(day.activities for day in response.itinerary_days)
    assert response.itinerary_days[0].destination == "en route"
    assert response.itinerary_days[-1].destination == "Hyderabad"
    assert all(
        any(
            activity.title.startswith(("Drive from", "Continue driving"))
            for activity in day.activities
        )
        for day in response.itinerary_days
    )
    assert any(
        activity.title == "Stay in Puducherry"
        for day in response.itinerary_days
        for activity in day.activities
    )


@pytest.mark.asyncio
async def test_short_verified_road_route_is_feasible(settings: Settings) -> None:
    response = await _run_road_plan(
        settings,
        distance_km=Decimal("100"),
        duration_minutes=120,
        deadline=datetime(2026, 10, 30, 18, tzinfo=INDIA_TIME_ZONE),
    )
    assert response.feasible is True
    assert response.status == "completed"
    assert response.route_legs[-1].arrival_at == datetime(
        2026, 10, 30, 16, tzinfo=INDIA_TIME_ZONE
    )
    assert response.budget.known_subtotal >= Decimal("2400.00")
    assert response.data_sources[0].name == "osrm"
    assert all(option.provider == "osrm+fuel_formula" for option in response.transport_options)


@pytest.mark.asyncio
async def test_same_day_start_uses_next_sensible_slot_and_warns(settings: Settings) -> None:
    fixed_now = datetime(2026, 10, 30, 14, 10, tzinfo=INDIA_TIME_ZONE)
    response = await _run_road_plan(
        settings,
        distance_km=Decimal("50"),
        duration_minutes=60,
        deadline=datetime(2026, 10, 31, 12, tzinfo=INDIA_TIME_ZONE),
        now=fixed_now,
    )
    assert response.route_legs[0].departure_at == datetime(
        2026, 10, 30, 14, 30, tzinfo=INDIA_TIME_ZONE
    )
    shift_warning = next(
        warning for warning in response.warnings if warning.startswith("Schedule start shifted")
    )
    assert "adds 17.0 hours to the return arrival" in shift_warning
    assert all(
        activity.starts_at is not None and activity.starts_at >= fixed_now
        for day in response.itinerary_days
        for activity in day.activities
    )

    stay = next(
        activity
        for day in response.itinerary_days
        for activity in day.activities
        if activity.title == "Stay in Puducherry"
    )
    assert stay.starts_at is not None
    assert stay.ends_at is not None
    assert (stay.ends_at - stay.starts_at).total_seconds() >= 6 * 3600
    next_leg = response.route_legs[1]
    assert next_leg.departure_at == stay.ends_at
    destination_hotel = next(
        hotel for hotel in response.hotels if hotel.destination == "Puducherry"
    )
    assert destination_hotel.check_in == stay.starts_at.date()
    assert destination_hotel.check_out == next_leg.departure_at.date()


@pytest.mark.asyncio
async def test_return_deadline_calculation_includes_destination_stay(
    settings: Settings,
) -> None:
    response = await _run_road_plan(
        settings,
        distance_km=Decimal("100"),
        duration_minutes=120,
        deadline=datetime(2026, 10, 30, 15, tzinfo=INDIA_TIME_ZONE),
    )
    assert response.route_legs[0].arrival_at == datetime(
        2026, 10, 30, 8, tzinfo=INDIA_TIME_ZONE
    )
    assert response.route_legs[1].departure_at == datetime(
        2026, 10, 30, 14, tzinfo=INDIA_TIME_ZONE
    )
    assert response.route_legs[1].arrival_at == datetime(
        2026, 10, 30, 16, tzinfo=INDIA_TIME_ZONE
    )
    assert response.feasible is False
    assert any("misses the required return deadline" in warning for warning in response.warnings)


@pytest.mark.asyncio
async def test_configured_minimum_stay_is_applied_to_every_destination(
    settings: Settings,
) -> None:
    response = await _run_road_plan(
        settings,
        distance_km=Decimal("50"),
        duration_minutes=60,
        deadline=datetime(2026, 10, 31, 12, tzinfo=INDIA_TIME_ZONE),
        min_stay_hours=8,
    )
    stays = [
        activity
        for day in response.itinerary_days
        for activity in day.activities
        if activity.title.startswith("Stay in ")
    ]
    assert {stay.location for stay in stays} == {"Puducherry"}
    assert all(stay.starts_at is not None and stay.ends_at is not None for stay in stays)
    assert all(
        (stay.ends_at - stay.starts_at).total_seconds() >= 8 * 3600  # type: ignore[operator]
        for stay in stays
    )


@pytest.mark.asyncio
async def test_past_start_date_asks_for_clarification_without_research(
    settings: Settings,
) -> None:
    requirements = TripRequirements(
        origin="Hyderabad",
        destinations=["Puducherry"],
        start_date=date(2026, 10, 29),
        end_date=date(2026, 10, 30),
    )

    def research_must_not_run(_fetched_at: datetime) -> NoReturn:
        raise AssertionError("research ran for a past-date clarification")

    response = await LangGraphTripPlanner(
        settings,
        intent_model=StaticIntentModel(requirements),
        provider_factory=research_must_not_run,
        now_provider=lambda: datetime(2026, 10, 30, 12, 0, tzinfo=INDIA_TIME_ZONE),
    ).run(
        conversation_id=None,
        user_prompt="past date",
        previous_trip=None,
        chat_mode="saved",
    )
    assert response.status == "needs_clarification"
    assert response.warnings == [
        "Start date is in the past",
        "What future start date should I use?",
    ]
    assert response.route_legs == []


@pytest.mark.asyncio
async def test_stub_mode_remains_unverified(settings: Settings) -> None:
    requirements = TripRequirements(
        origin="Hyderabad",
        destinations=["Puducherry"],
        start_date=date(2026, 10, 30),
        end_date=date(2026, 10, 30),
        return_deadline=datetime(2026, 10, 31, 18, tzinfo=INDIA_TIME_ZONE),
    )
    response = await LangGraphTripPlanner(
        settings,
        intent_model=StaticIntentModel(requirements),
        now_provider=lambda: datetime(2026, 10, 30, 5, 0, tzinfo=INDIA_TIME_ZONE),
    ).run(
        conversation_id=None,
        user_prompt="stub mode",
        previous_trip=None,
        chat_mode="temporary",
    )
    assert response.feasible is None
    assert all(leg.duration_source == "stub" for leg in response.route_legs)
    assert "Based on road travel estimates only" not in " ".join(response.warnings)
