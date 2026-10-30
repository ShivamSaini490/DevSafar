
from typing import Any

from app.agents.state import TravelState
from app.services.budget_service import BudgetService
from app.services.itinerary_service import ItineraryService
from app.services.route_service import RouteService


async def planning_node(state: TravelState) -> dict[str, Any]:
    requirements = state["requirements"]
    if requirements is None:
        raise ValueError("Planning requires trip requirements")
    is_retry = bool(state["validation_errors"])
    return {
        "route_options": RouteService.build_route(state["route_options"]),
        "itinerary": ItineraryService.build(requirements),
        "budget_breakdown": BudgetService.build(
            transport_options=state["transport_options"],
            hotels=state["hotels"],
            attractions=state["attractions"],
        ),
        "retry_count": state["retry_count"] + (1 if is_retry else 0),
        "validation_errors": [],
    }
