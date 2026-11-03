from collections.abc import Callable
from datetime import datetime
from typing import Any

from app.agents.state import TravelState
from app.core.config import Settings
from app.schemas.common import DataSource
from app.services.budget_service import BudgetService
from app.services.fare_estimator import FareEstimator
from app.services.itinerary_service import ItineraryService
from app.services.price_engine import PriceEngine
from app.services.route_service import RouteService
from app.utils.datetime_utils import at_india_time, india_now


def build_planning_node(
    settings: Settings,
    *,
    now_provider: Callable[[], datetime] = india_now,
    price_engine: PriceEngine | None = None,
) -> Any:
    async def planning_node(state: TravelState) -> dict[str, Any]:
        requirements = state["requirements"]
        if requirements is None:
            raise ValueError("Planning requires trip requirements")
        is_retry = bool(state["validation_errors"])
        planning_now = now_provider()
        route_legs = RouteService.build_route(
            requirements,
            state["route_options"],
            use_stub_defaults=settings.maps_provider == "stub",
            max_driving_hours_per_day=settings.max_driving_hours_per_day,
            driving_latest_arrival_hour=settings.driving_latest_arrival_hour,
            min_stay_hours_per_destination=settings.min_stay_hours_per_destination,
            now=planning_now,
        )
        baseline_return_at: datetime | None = None
        first_departure = route_legs[0].departure_at if route_legs else None
        if (
            requirements.start_date is not None
            and first_departure is not None
            and first_departure
            > at_india_time(requirements.start_date, hour=6)
        ):
            baseline_legs = RouteService.build_route(
                requirements,
                state["route_options"],
                use_stub_defaults=settings.maps_provider == "stub",
                max_driving_hours_per_day=settings.max_driving_hours_per_day,
                driving_latest_arrival_hour=settings.driving_latest_arrival_hour,
                min_stay_hours_per_destination=settings.min_stay_hours_per_destination,
                now=at_india_time(requirements.start_date, hour=5),
            )
            baseline_return_at = next(
                (
                    leg.arrival_at
                    for leg in reversed(baseline_legs)
                    if leg.arrival_at is not None
                ),
                None,
            )
        fetched_at = state["fetched_at"]
        if fetched_at is None:
            raise ValueError("Planning requires fetched_at")
        fare_plan = FareEstimator(settings).build(
            requirements=requirements,
            road_legs=route_legs,
            fetched_at=fetched_at,
        )
        price_sources: list[DataSource] = []
        price_warnings: list[str] = []
        if price_engine is not None:
            fare_plan, price_sources, price_warnings = await price_engine.enrich_plan(
                trip_id=state["trip_id"],
                requirements=requirements,
                plan=fare_plan,
                persist_history=state["chat_mode"] != "temporary",
            )
        selected_comparison = next(
            (
                comparison
                for comparison in fare_plan.mode_comparison
                if comparison.recommended is True
            ),
            None,
        )
        budget = BudgetService.build_estimated_range(
            comparison=selected_comparison,
            hotel_total_min=fare_plan.hotel_total_min,
            hotel_total_max=fare_plan.hotel_total_max,
            food_total_min=fare_plan.food_total_min,
            food_total_max=fare_plan.food_total_max,
            local_transport_total_min=fare_plan.local_transport_total_min,
            local_transport_total_max=fare_plan.local_transport_total_max,
            attractions=state["attractions"],
            fetched_at=fetched_at,
        )
        if fare_plan.recommended_mode not in {None, "road"}:
            itinerary = ItineraryService.build_estimated_mode(
                requirements,
                fare_plan.route_legs,
            )
        else:
            itinerary = ItineraryService.build(
                requirements,
                fare_plan.route_legs,
                attractions=state["attractions"],
                min_stay_hours_per_destination=settings.min_stay_hours_per_destination,
                now=planning_now,
            )
        provider_sources = [
            source
            for source in state["provider_sources"]
            if source.name
            not in {
                "stub_transport",
                "stub_hotels",
                "distance_formula",
                "tier_assumption",
                "configured_estimates",
            }
        ]
        provider_sources.extend(
            [
                DataSource(
                    name="distance_formula",
                    price_type="estimate",
                    fetched_at=fetched_at,
                    status=(
                        "ok"
                        if selected_comparison is not None
                        else "degraded"
                    ),
                ),
                DataSource(
                    name="tier_assumption",
                    price_type="estimate",
                    fetched_at=fetched_at,
                    status="ok",
                ),
                DataSource(
                    name="configured_estimates",
                    price_type="estimate",
                    fetched_at=fetched_at,
                    status="ok",
                ),
            ]
        )
        provider_sources.extend(price_sources)
        budget_warnings: list[str] = []
        if budget.estimated_total_min is not None:
            if requirements.budget is None:
                budget_warnings.append(
                    "No budget was provided; use the estimated total range as a suggested budget."
                )
            elif budget.estimated_total_min > requirements.budget:
                budget_warnings.append(
                    "The minimum estimated total exceeds the requested budget."
                )
        return {
            "route_options": fare_plan.route_legs,
            "transport_options": fare_plan.transport_options,
            "hotels": fare_plan.hotels,
            "itinerary": itinerary,
            "budget_breakdown": budget,
            "mode_comparison": fare_plan.mode_comparison,
            "provider_sources": provider_sources,
            "retry_count": state["retry_count"] + (1 if is_retry else 0),
            "validation_errors": [],
            "warnings": list(
                dict.fromkeys(
                    [
                        *state["warnings"],
                        *(
                            RouteService.schedule_warnings(
                                fare_plan.route_legs,
                                daily_hours=settings.max_driving_hours_per_day,
                                latest_arrival_hour=settings.driving_latest_arrival_hour,
                                start_date=requirements.start_date,
                                baseline_return_at=baseline_return_at,
                            )
                            if fare_plan.recommended_mode == "road"
                            else []
                        ),
                        *fare_plan.warnings,
                        *price_warnings,
                        *budget_warnings,
                        *(
                            [
                                "Road cost assumes a private car at INR "
                                f"{settings.fuel_cost_per_km:f} per km; adjust "
                                "FUEL_COST_PER_KM.",
                                "OSRM durations exclude traffic, so real travel time may be longer.",
                            ]
                            if fare_plan.recommended_mode == "road"
                            else []
                        ),
                    ]
                )
            ),
        }

    return planning_node
