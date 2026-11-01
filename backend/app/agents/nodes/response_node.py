from typing import Any

from app.agents.state import TravelState
from app.core.config import Settings
from app.schemas.budget import empty_budget
from app.schemas.trip import TripResponse, TripStatus
from app.services.booking_service import BookingService

INFEASIBLE_ALTERNATIVES = (
    "Alternative 1: Use the train, bus, or flight search links in booking_links.",
    "Alternative 2: Extend the trip dates or return deadline.",
    "Alternative 3: Drop a destination.",
    "Alternative 4: Increase the budget.",
)
ASSUMPTION_PREFIXES = (
    "Travelers not specified;",
    "Return time not specified;",
    "Schedule start shifted",
)


def _ordered_warnings(
    *,
    errors: list[str],
    details: list[str],
) -> list[str]:
    assumptions = [warning for warning in details if warning.startswith(ASSUMPTION_PREFIXES)]
    supporting_details = [
        warning for warning in details if not warning.startswith(ASSUMPTION_PREFIXES)
    ]
    alternatives = list(INFEASIBLE_ALTERNATIVES) if errors else []
    return list(dict.fromkeys([*errors, *assumptions, *supporting_details, *alternatives]))


def build_response_node(settings: Settings) -> Any:
    booking_service = BookingService(settings)

    async def response_node(state: TravelState) -> dict[str, Any]:
        requirements = state["requirements"]
        if requirements is None:
            raise ValueError("Response requires trip requirements")
        errors = state["validation_errors"]
        warnings = _ordered_warnings(errors=errors, details=state["warnings"])
        status: TripStatus = "failed" if state["status"] == "failed" else "completed"
        response = TripResponse(
            trip_id=state["trip_id"],
            status=status,
            requirements=requirements,
            feasible=state["feasible"],
            warnings=warnings,
            route_legs=state["route_options"],
            transport_options=state["transport_options"],
            hotels=state["hotels"],
            attractions=state["attractions"],
            itinerary_days=state["itinerary"],
            budget=state["budget_breakdown"] or empty_budget(),
            data_sources=state["provider_sources"],
            booking_links=booking_service.build(
                requirements,
                state["route_options"],
                state["hotels"],
            ),
        )
        return {
            "status": response.status,
            "warnings": response.warnings,
            "final_response": response,
        }

    return response_node
