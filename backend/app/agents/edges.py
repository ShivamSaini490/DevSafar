
from typing import Literal

from app.agents.state import TravelState
from app.core.constants import MAX_PLANNING_RETRIES


def after_intent(state: TravelState) -> Literal["research", "end"]:
    return "end" if state["status"] == "needs_clarification" else "research"


def after_validation(state: TravelState) -> Literal["planning", "response"]:
    if state["validation_errors"] and state["retry_count"] < MAX_PLANNING_RETRIES:
        return "planning"
    return "response"
