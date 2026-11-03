from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pytest

from app.agents.graph import LangGraphTripPlanner
from app.core.config import Settings
from app.core.security import utc_now
from app.integrations.base import ProviderBundle
from app.schemas.common import PriceQuote
from app.schemas.transport import RouteLeg
from app.schemas.trip import TripRequirements, TripResponse
from app.services.fare_estimator import FareEstimator
from app.services.route_service import ordered_route_stops
from app.utils.datetime_utils import INDIA_TIME_ZONE

FIXED_NOW = datetime(2026, 11, 2, 9, 0, tzinfo=INDIA_TIME_ZONE)


def _requirements(*, deadline: datetime | None = None) -> TripRequirements:
    return TripRequirements(
        origin="Hyderabad",
        destinations=["Delhi"],
        start_date=date(2026, 11, 9),
        end_date=date(2026, 11, 11),
        travelers=1,
        budget=None,
        return_deadline=deadline,
        return_to_origin=True,
    )


def _road_legs(requirements: TripRequirements) -> list[RouteLeg]:
    fetched_at = utc_now()
    stops = ordered_route_stops(requirements)
    return [
        RouteLeg(
            origin=origin,
            destination=destination,
            mode="road",
            duration_minutes=960,
            duration_source="osrm",
            distance_km=Decimal("1500.125"),
            great_circle_distance_km=Decimal("1255.500"),
            price=PriceQuote(
                amount=Decimal("18001.50"),
                price_type="estimate",
                source="fuel_formula",
                fetched_at=fetched_at,
            ),
        )
        for origin, destination in zip(stops, stops[1:], strict=False)
    ]


def test_estimates_are_decimal_ranges_and_never_live(settings: Settings) -> None:
    requirements = _requirements()
    plan = FareEstimator(settings).build(
        requirements=requirements,
        road_legs=_road_legs(requirements),
        fetched_at=FIXED_NOW,
    )

    assert {item.mode for item in plan.mode_comparison} == {
        "road",
        "train",
        "bus",
        "flight",
    }
    assert plan.recommended_mode is not None
    assert {hotel.tier for hotel in plan.hotels} == {
        "budget",
        "standard",
        "comfort",
    }
    prices = [
        *(option.price for option in plan.transport_options),
        *(hotel.nightly_price for hotel in plan.hotels),
        *(hotel.total_price for hotel in plan.hotels),
    ]
    assert all(price.price_type != "live_quote" for price in prices)
    for price in prices:
        if price.price_type == "estimate":
            assert isinstance(price.amount_min, Decimal)
            assert isinstance(price.amount_max, Decimal)
            assert price.amount_min <= price.amount_max
            assert price.source in {"distance_formula", "tier_assumption"}
            assert price.fetched_at == FIXED_NOW


def test_flight_without_airport_mapping_is_unknown(settings: Settings) -> None:
    requirements = TripRequirements(
        origin="Unmapped Alpha",
        destinations=["Unmapped Beta"],
        start_date=date(2026, 11, 9),
        end_date=date(2026, 11, 11),
        return_to_origin=True,
    )
    legs = _road_legs(requirements)
    plan = FareEstimator(settings).build(
        requirements=requirements,
        road_legs=legs,
        fetched_at=FIXED_NOW,
    )

    flights = [item for item in plan.transport_options if item.mode == "flight"]
    assert flights
    assert all(item.price.price_type == "unknown" for item in flights)
    assert all(item.price.amount is None for item in flights)
    assert all(item.price.amount_min is None for item in flights)
    assert all("nearest airport must be checked" in (item.note or "") for item in flights)


def test_deadline_selects_cheapest_meeting_mode_else_fastest(settings: Settings) -> None:
    generous = _requirements(
        deadline=datetime(2026, 11, 20, 23, 59, tzinfo=INDIA_TIME_ZONE)
    )
    generous_plan = FareEstimator(settings).build(
        requirements=generous,
        road_legs=_road_legs(generous),
        fetched_at=FIXED_NOW,
    )
    assert generous_plan.recommended_mode == "train"
    assert next(
        item for item in generous_plan.mode_comparison if item.mode == "train"
    ).meets_deadline_estimate is True

    tight = _requirements(
        deadline=datetime(2026, 11, 9, 12, 0, tzinfo=INDIA_TIME_ZONE)
    )
    tight_plan = FareEstimator(settings).build(
        requirements=tight,
        road_legs=_road_legs(tight),
        fetched_at=FIXED_NOW,
    )
    assert not any(
        item.meets_deadline_estimate is True for item in tight_plan.mode_comparison
    )
    assert tight_plan.recommended_mode == "flight"


class VagueIntentModel:
    async def extract_requirements(
        self,
        *,
        user_prompt: str,
        previous_trip: TripResponse | None,
    ) -> TripRequirements:
        del user_prompt, previous_trip
        return TripRequirements(
            origin="Hyderabad",
            destinations=["Delhi"],
            start_date=None,
            end_date=None,
            travelers=1,
            budget=None,
            return_deadline=None,
            return_to_origin=None,
            ambiguities=["Travelers not specified; assuming 1."],
        )


class StaticDistanceMaps:
    async def route_legs(self, requirements: TripRequirements) -> list[RouteLeg]:
        return _road_legs(requirements)


@pytest.mark.asyncio
async def test_vague_prompt_completes_with_assumptions_and_estimates(
    settings: Settings,
) -> None:
    def providers(fetched_at: datetime) -> ProviderBundle:
        del fetched_at
        return ProviderBundle.stubs(FIXED_NOW).with_maps(
            StaticDistanceMaps(),
            source_name="osrm",
        )

    response = await LangGraphTripPlanner(
        settings,
        intent_model=VagueIntentModel(),
        provider_factory=providers,
        now_provider=lambda: FIXED_NOW,
    ).run(
        conversation_id=None,
        user_prompt="Hyderabad se Delhi jana hai",
        previous_trip=None,
        chat_mode="temporary",
    )

    assert response.status == "completed"
    assert response.requirements.start_date == date(2026, 11, 9)
    assert response.requirements.end_date == date(2026, 11, 11)
    assert response.requirements.return_to_origin is True
    assert len(response.assumptions) == 5
    assert 2 <= len(response.suggested_followups) <= 3
    assert {item.mode for item in response.mode_comparison} == {
        "road",
        "train",
        "bus",
        "flight",
    }
    assert any(item.recommended is True for item in response.mode_comparison)
    assert {hotel.tier for hotel in response.hotels} == {
        "budget",
        "standard",
        "comfort",
    }
    assert response.budget.estimated_total_min is not None
    assert response.budget.estimated_total_max is not None
    assert response.budget.estimated_total_min <= response.budget.estimated_total_max
    assert response.feasible is None
    assert (
        "No budget was provided; use the estimated total range as a suggested budget."
        in response.warnings
    )
    assert all(
        activity.starts_at is None and activity.ends_at is None
        for day in response.itinerary_days
        for activity in day.activities
    )


@pytest.mark.parametrize(
    "requirements",
    [
        TripRequirements(origin=None, destinations=["Delhi"]),
        TripRequirements(origin="Hyderabad", destinations=[]),
    ],
)
@pytest.mark.asyncio
async def test_missing_origin_or_destination_still_clarifies(
    settings: Settings,
    requirements: TripRequirements,
) -> None:
    class MissingIntent:
        async def extract_requirements(self, **_kwargs: Any) -> TripRequirements:
            return requirements.model_copy(deep=True)

    response = await LangGraphTripPlanner(
        settings,
        intent_model=MissingIntent(),
        now_provider=lambda: FIXED_NOW,
    ).run(
        conversation_id=None,
        user_prompt="vague",
        previous_trip=None,
        chat_mode="temporary",
    )

    assert response.status == "needs_clarification"
    assert response.mode_comparison == []


@pytest.mark.asyncio
async def test_budget_below_estimated_min_adds_warning(settings: Settings) -> None:
    class LowBudgetIntent:
        async def extract_requirements(self, **_kwargs: Any) -> TripRequirements:
            return TripRequirements(
                origin="Hyderabad",
                destinations=["Delhi"],
                start_date=date(2026, 11, 9),
                end_date=date(2026, 11, 11),
                budget=Decimal("100"),
                return_to_origin=True,
            )

    def providers(fetched_at: datetime) -> ProviderBundle:
        del fetched_at
        return ProviderBundle.stubs(FIXED_NOW).with_maps(
            StaticDistanceMaps(),
            source_name="osrm",
        )

    response = await LangGraphTripPlanner(
        settings,
        intent_model=LowBudgetIntent(),
        provider_factory=providers,
        now_provider=lambda: FIXED_NOW,
    ).run(
        conversation_id=None,
        user_prompt="low budget",
        previous_trip=None,
        chat_mode="saved",
    )

    assert response.budget.estimated_total_min is not None
    assert response.budget.estimated_total_min > Decimal("100")
    assert "The minimum estimated total exceeds the requested budget." in response.warnings
