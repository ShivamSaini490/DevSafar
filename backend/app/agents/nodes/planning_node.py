from typing import Any

from app.agents.state import TravelState
from app.core.config import Settings
from app.services.budget_service import BudgetService
from app.services.hotel_service import HotelService
from app.services.itinerary_service import ItineraryService
from app.services.route_service import RouteService


def build_planning_node(settings: Settings) -> Any:
    async def planning_node(state: TravelState) -> dict[str, Any]:
        requirements = state["requirements"]
        if requirements is None:
            raise ValueError("Planning requires trip requirements")
        is_retry = bool(state["validation_errors"])
        route_legs = RouteService.build_route(
            requirements,
            state["route_options"],
            use_stub_defaults=settings.maps_provider == "stub",
            max_driving_hours_per_day=settings.max_driving_hours_per_day,
        )
        hotels = HotelService.align_with_route(
            requirements,
            route_legs,
            state["hotels"],
        )
        return {
            "route_options": route_legs,
            "hotels": hotels,
            "itinerary": ItineraryService.build(requirements, route_legs),
            "budget_breakdown": BudgetService.build(
                requirements=requirements,
                route_legs=route_legs,
                transport_options=state["transport_options"],
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
                        ),
                        *(
                            [
                                "Based on road travel estimates only; trains, buses and "
                                "flights are not compared yet."
                            ]
                            if settings.maps_provider == "osm"
                            else []
                        ),
                    ]
                )
            ),
        }

    return planning_node
