
from typing import Any

from app.agents.state import TravelState
from app.services.itinerary_service import ItineraryService
from app.utils.currency_utils import sum_known_amounts


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
    planned_return = ItineraryService.planned_return_at(requirements)
    if (
        planned_return is not None
        and requirements.return_deadline is not None
        and planned_return > requirements.return_deadline
    ):
        errors.append("The planned return misses the required return deadline.")
    known_total = sum_known_amounts(category.amount for category in budget.categories)
    if requirements.budget is not None and known_total > requirements.budget:
        errors.append("Known estimated costs exceed the requested budget.")
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
        price.price_type == "live_quote" and price.source == "stub"
        for price in all_prices
    ):
        errors.append("Stub data cannot be labelled as a live quote.")
    return {
        "validation_errors": list(dict.fromkeys(errors)),
        "warnings": list(dict.fromkeys(warnings)),
    }
