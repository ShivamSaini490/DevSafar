from collections.abc import Callable
from datetime import datetime
from typing import Any

from app.agents.state import TravelState
from app.core.config import Settings
from app.services.budget_service import BudgetService
from app.services.hotel_service import HotelService
from app.services.itinerary_service import ItineraryService
from app.services.route_service import RouteService
from app.services.transport_service import TransportService
from app.utils.datetime_utils import at_india_time, india_now


def build_planning_node(
    settings: Settings,
    *,
    now_provider: Callable[[], datetime] = india_now,
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
        transport_options = (
            TransportService.from_route_legs(route_legs)
            if settings.maps_provider == "osm"
            else state["transport_options"]
        )
        hotels = HotelService.align_with_route(
            requirements,
            route_legs,
            state["hotels"],
            min_stay_hours_per_destination=settings.min_stay_hours_per_destination,
        )
        return {
            "route_options": route_legs,
            "transport_options": transport_options,
            "hotels": hotels,
            "itinerary": ItineraryService.build(
                requirements,
                route_legs,
                min_stay_hours_per_destination=settings.min_stay_hours_per_destination,
                now=planning_now,
            ),
            "budget_breakdown": BudgetService.build(
                requirements=requirements,
                route_legs=route_legs,
                transport_options=transport_options,
                hotels=hotels,
                attractions=state["attractions"],
                food_per_day_per_traveler=(settings.food_estimate_per_day_per_traveler),
                buffer_percent=settings.budget_buffer_percent,
            ),
            "retry_count": state["retry_count"] + (1 if is_retry else 0),
            "validation_errors": [],
            "warnings": list(
                dict.fromkeys(
                    [
                        *state["warnings"],
                        *RouteService.schedule_warnings(
                            route_legs,
                            daily_hours=settings.max_driving_hours_per_day,
                            start_date=requirements.start_date,
                            baseline_return_at=baseline_return_at,
                        ),
                        *(
                            [
                                "Based on road travel estimates only; trains, buses and "
                                "flights are not compared yet."
                            ]
                            if settings.maps_provider == "osm"
                            else []
                        ),
                        *(
                            [
                                "Road cost assumes a private car at INR "
                                f"{settings.fuel_cost_per_km:f} per km; adjust "
                                "FUEL_COST_PER_KM.",
                                "OSRM durations exclude traffic, so real travel time may be longer.",
                            ]
                            if settings.maps_provider == "osm"
                            else []
                        ),
                    ]
                )
            ),
        }

    return planning_node
