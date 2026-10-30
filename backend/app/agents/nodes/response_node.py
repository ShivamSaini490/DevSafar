from typing import Any
from uuid import uuid4

from app.agents.state import TravelState
from app.schemas.budget import empty_budget
from app.schemas.trip import TripResponse, TripStatus

INFEASIBLE_ALTERNATIVES = (
    "Alternative 1: Compare train/bus/flight options (not integrated yet; links to official "
    "search pages are coming).",
    "Alternative 2: Extend the trip dates or return deadline.",
    "Alternative 3: Drop a destination.",
    "Alternative 4: Increase the budget.",
)


async def response_node(state: TravelState) -> dict[str, Any]:
    requirements = state["requirements"]
    if requirements is None:
        raise ValueError("Response requires trip requirements")
    errors = state["validation_errors"]
    warnings = [*state["warnings"], *errors]
    if errors:
        warnings.extend(INFEASIBLE_ALTERNATIVES)
    status: TripStatus = "failed" if state["status"] == "failed" else "completed"
    response = TripResponse(
        trip_id=uuid4(),
        status=status,
        requirements=requirements,
        feasible=state["feasible"],
        warnings=list(dict.fromkeys(warnings)),
        route_legs=state["route_options"],
        transport_options=state["transport_options"],
        hotels=state["hotels"],
        attractions=state["attractions"],
        itinerary_days=state["itinerary"],
        budget=state["budget_breakdown"] or empty_budget(),
        data_sources=state["provider_sources"],
        booking_links=[],
    )
    return {
        "status": response.status,
        "warnings": response.warnings,
        "final_response": response,
    }
