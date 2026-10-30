
from typing import Any
from uuid import uuid4

from app.agents.state import TravelState
from app.schemas.budget import empty_budget
from app.schemas.trip import TripResponse


async def response_node(state: TravelState) -> dict[str, Any]:
    requirements = state["requirements"]
    if requirements is None:
        raise ValueError("Response requires trip requirements")
    errors = state["validation_errors"]
    warnings = [*state["warnings"], *errors]
    if errors:
        warnings.append(
            "Safer alternative: increase the budget or relax the return deadline."
        )
    response = TripResponse(
        trip_id=uuid4(),
        status="failed" if errors else "completed",
        requirements=requirements,
        feasible=not errors,
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
