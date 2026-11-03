import re
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from app.agents.llm import RETURN_TIME_ASSUMPTION, IntentModel
from app.agents.state import TravelState
from app.schemas.budget import empty_budget
from app.schemas.trip import TripRequirements, TripResponse
from app.utils.datetime_utils import india_now

TRAVELER_ASSUMPTION = "Travelers not specified; assuming 1."
BUDGET_ASSUMPTION = "Budget not specified; showing a suggested estimate range."
RETURN_ASSUMPTION = "Return preference not specified; assuming return to origin."


def _valid_place(value: str | None) -> bool:
    return bool(value and re.search(r"[A-Za-z0-9]", value))


def _apply_defaults_and_questions(
    requirements: TripRequirements,
    *,
    now: datetime,
) -> tuple[list[str], list[str]]:
    questions: list[str] = []
    assumptions: list[str] = []
    if not _valid_place(requirements.origin):
        questions.append("Which city are you starting from?")
    if not requirements.destinations or any(
        not _valid_place(destination) for destination in requirements.destinations
    ):
        questions.append("Which destinations do you want to visit?")
    invalid_start = "Start date is invalid." in requirements.ambiguities
    invalid_end = "End date is invalid." in requirements.ambiguities
    if requirements.start_date is None:
        if invalid_start:
            questions.append("What valid future start date should I use?")
        else:
            requirements.start_date = now.date() + timedelta(days=7)
            assumptions.append(
                "Start date not specified; using "
                f"{requirements.start_date.isoformat()} (7 days from today)."
            )
    if requirements.end_date is None:
        if invalid_end:
            questions.append("What valid trip end date should I use?")
        elif requirements.start_date is not None:
            requirements.end_date = requirements.start_date + timedelta(days=2)
            assumptions.append("Trip length not specified; using 3 days.")
    if requirements.start_date is not None and requirements.start_date < now.date():
        questions.extend(
            [
                "Start date is in the past",
                "What future start date should I use?",
            ]
        )
    if requirements.end_date is not None and requirements.end_date < now.date():
        questions.extend(
            [
                "End date is in the past",
                "What future trip dates should I use?",
            ]
        )
    if (
        requirements.start_date is not None
        and requirements.end_date is not None
        and requirements.end_date < requirements.start_date
    ):
        questions.append("Your end date is before your start date. What dates should I use?")
    if TRAVELER_ASSUMPTION in requirements.ambiguities:
        assumptions.append(TRAVELER_ASSUMPTION)
    if requirements.budget is None:
        assumptions.append(BUDGET_ASSUMPTION)
    if requirements.return_to_origin is None:
        requirements.return_to_origin = True
        assumptions.append(RETURN_ASSUMPTION)
    if RETURN_TIME_ASSUMPTION in requirements.ambiguities:
        assumptions.append(RETURN_TIME_ASSUMPTION)
    return list(dict.fromkeys(questions)), list(dict.fromkeys(assumptions))


def _suggested_followups(
    requirements: TripRequirements,
    assumptions: list[str],
    questions: list[str],
) -> list[str]:
    suggestions: list[str] = []
    if any("starting" in question.casefold() for question in questions):
        suggestions.append("Tell me your starting city")
    if any("destination" in question.casefold() for question in questions):
        suggestions.append("Tell me your destination")
    if any("date" in item.casefold() for item in [*questions, *assumptions]):
        suggestions.append("Tell me your exact dates")
    if requirements.budget is None:
        suggestions.append("Add a budget")
    if not requirements.preferences:
        suggestions.append("Prefer train or flight?")
    fallbacks = ("Change the trip length", "Add a return deadline")
    suggestions.extend(item for item in fallbacks if item not in suggestions)
    return list(dict.fromkeys(suggestions))[:3]


def build_intent_node(
    intent_model: IntentModel,
    *,
    now_provider: Callable[[], datetime] = india_now,
) -> Any:
    async def intent_node(state: TravelState) -> dict[str, Any]:
        requirements = await intent_model.extract_requirements(
            user_prompt=state["user_prompt"],
            previous_trip=state["previous_trip"],
        )
        questions, assumptions = _apply_defaults_and_questions(
            requirements,
            now=now_provider(),
        )
        suggested_followups = _suggested_followups(
            requirements,
            assumptions,
            questions,
        )
        requirements.ambiguities = []
        if questions:
            response = TripResponse(
                trip_id=state["trip_id"],
                status="needs_clarification",
                requirements=requirements,
                feasible=None,
                warnings=questions,
                assumptions=assumptions,
                suggested_followups=suggested_followups,
                route_legs=[],
                transport_options=[],
                hotels=[],
                attractions=[],
                itinerary_days=[],
                budget=empty_budget(),
                data_sources=[],
                booking_links=[],
                mode_comparison=[],
            )
            return {
                "requirements": requirements,
                "status": "needs_clarification",
                "warnings": questions,
                "assumptions": assumptions,
                "suggested_followups": suggested_followups,
                "final_response": response,
            }
        return {
            "requirements": requirements,
            "status": "completed",
            "warnings": [],
            "assumptions": assumptions,
            "suggested_followups": suggested_followups,
        }

    return intent_node
