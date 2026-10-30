from typing import Any
from uuid import uuid4

from app.agents.llm import IntentModel
from app.agents.state import TravelState
from app.schemas.budget import empty_budget
from app.schemas.trip import TripRequirements, TripResponse


def _critical_questions(requirements: TripRequirements) -> list[str]:
    questions: list[str] = []
    if not requirements.origin:
        questions.append("Which city are you starting from?")
    if not requirements.destinations:
        questions.append("Which destinations do you want to visit?")
    if requirements.start_date is None:
        questions.append("What is your trip start date?")
    if requirements.end_date is None:
        questions.append("What is your trip end date?")
    if (
        requirements.start_date is not None
        and requirements.end_date is not None
        and requirements.end_date < requirements.start_date
    ):
        questions.append("Your end date is before your start date. What dates should I use?")
    return questions


def _assumption_warning(ambiguity: str) -> str | None:
    cleaned = " ".join(ambiguity.split())
    if not cleaned:
        return None
    normalized = cleaned.casefold()
    if "traveler" in normalized or "passenger" in normalized:
        return "Travelers not specified; assuming 1."
    if "time zone" in normalized or "timezone" in normalized:
        return "Return deadline timezone assumed Asia/Kolkata."
    return cleaned


def _planning_warnings(requirements: TripRequirements) -> list[str]:
    warnings = [
        warning
        for ambiguity in requirements.ambiguities
        if (warning := _assumption_warning(ambiguity)) is not None
    ]
    if requirements.budget is None:
        warnings.append("Budget not specified; planning with budget unknown.")
    if requirements.return_deadline is None:
        warnings.append("Return deadline not specified; deadline validation skipped.")
    return list(dict.fromkeys(warnings))


def build_intent_node(intent_model: IntentModel) -> Any:
    async def intent_node(state: TravelState) -> dict[str, Any]:
        requirements = await intent_model.extract_requirements(
            user_prompt=state["user_prompt"],
            previous_trip=state["previous_trip"],
        )
        questions = _critical_questions(requirements)
        if questions:
            response = TripResponse(
                trip_id=uuid4(),
                status="needs_clarification",
                requirements=requirements,
                feasible=False,
                warnings=questions,
                route_legs=[],
                transport_options=[],
                hotels=[],
                attractions=[],
                itinerary_days=[],
                budget=empty_budget(),
                data_sources=[],
                booking_links=[],
            )
            return {
                "requirements": requirements,
                "status": "needs_clarification",
                "warnings": questions,
                "final_response": response,
            }
        warnings = _planning_warnings(requirements)
        requirements.ambiguities = []
        return {
            "requirements": requirements,
            "status": "completed",
            "warnings": warnings,
        }

    return intent_node
