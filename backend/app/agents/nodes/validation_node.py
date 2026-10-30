from typing import Any

from app.agents.state import TravelState
from app.services.itinerary_service import ItineraryService

UNVERIFIED_TIMES_WARNING = "Feasibility cannot be verified: transport times are unverified/stub."


def _has_verified_durations(state: TravelState) -> bool:
    legs = state["route_options"]
    return bool(legs) and all(
        leg.duration_minutes is not None
        and leg.departure_at is not None
        and leg.arrival_at is not None
        and leg.duration_source is not None
        and not leg.duration_source.casefold().startswith("stub")
        for leg in legs
    )


async def validation_node(state: TravelState) -> dict[str, Any]:
    requirements = state["requirements"]
    budget = state["budget_breakdown"]
    if requirements is None or budget is None:
        raise ValueError("Validation requires a planned trip")
    errors: list[str] = []
    warnings = list(state["warnings"])
    if (
        requirements.start_date is not None
        and requirements.end_date is not None
        and requirements.end_date < requirements.start_date
    ):
        errors.append("Trip end date is before the start date.")

    return_arrival = ItineraryService.planned_return_at(
        requirements,
        state["route_options"],
    )
    if (
        return_arrival is not None
        and requirements.return_deadline is not None
        and return_arrival > requirements.return_deadline
    ):
        errors.append("The computed return arrival misses the required return deadline.")
    if requirements.budget is not None and budget.known_subtotal > requirements.budget:
        errors.append("Known subtotal already exceeds the requested budget.")

    all_prices = [
        *(leg.price for leg in state["route_options"]),
        *(option.price for option in state["transport_options"]),
        *(hotel.nightly_price for hotel in state["hotels"]),
        *(hotel.total_price for hotel in state["hotels"]),
        *(place.entry_fee for place in state["attractions"]),
    ]
    if any(price.price_type == "unknown" for price in all_prices):
        warnings.append("Some prices are unknown and must be verified before booking.")
    if any(
        price.price_type == "live_quote" and price.source.startswith("stub") for price in all_prices
    ):
        errors.append("Stub data cannot be labelled as a live quote.")

    verified_durations = _has_verified_durations(state)
    if errors:
        feasible: bool | None = False
    elif (
        verified_durations
        and return_arrival is not None
        and requirements.return_deadline is not None
        and return_arrival <= requirements.return_deadline
    ):
        feasible = True
    else:
        feasible = None
        if not verified_durations:
            warnings.append(UNVERIFIED_TIMES_WARNING)
    return {
        "validation_errors": list(dict.fromkeys(errors)),
        "feasible": feasible,
        "warnings": list(dict.fromkeys(warnings)),
    }
