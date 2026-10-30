from datetime import date, datetime
from decimal import Decimal

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
) -> TripResponse:
    osm_settings = settings.model_copy(update={"maps_provider": "osm"})
    requirements = TripRequirements(
        origin="Hyderabad",
        destinations=["Puducherry"],
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
    )
    return await planner.run(
        conversation_id=None,
        user_prompt="city-only fake provider test",
        previous_trip=None,
        chat_mode="saved",
    )


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
    assert response.status == "failed"
    assert len(response.route_legs) == 2
    assert sum(leg.overnight_stops for leg in response.route_legs) >= 2
    assert response.route_legs[-1].arrival_at is not None
    assert response.route_legs[-1].arrival_at > response.requirements.return_deadline
    assert any("misses the required return deadline" in warning for warning in response.warnings)
    assert any("overnight rest stop" in warning for warning in response.warnings)
    assert any("Safer alternative" in warning for warning in response.warnings)
    assert (
        "Based on road travel estimates only; trains, buses and flights are not compared yet."
        in response.warnings
    )


@pytest.mark.asyncio
async def test_short_verified_road_route_is_feasible(settings: Settings) -> None:
    response = await _run_road_plan(
        settings,
        distance_km=Decimal("100"),
        duration_minutes=120,
        deadline=datetime(2026, 10, 30, 12, tzinfo=INDIA_TIME_ZONE),
    )
    assert response.feasible is True
    assert response.status == "completed"
    assert response.route_legs[-1].arrival_at == datetime(
        2026, 10, 30, 10, tzinfo=INDIA_TIME_ZONE
    )
    assert response.budget.known_subtotal >= Decimal("2400.00")
    assert response.data_sources[0].name == "osrm"


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
    ).run(
        conversation_id=None,
        user_prompt="stub mode",
        previous_trip=None,
        chat_mode="temporary",
    )
    assert response.feasible is None
    assert all(leg.duration_source == "stub" for leg in response.route_legs)
    assert "Based on road travel estimates only" not in " ".join(response.warnings)
