import asyncio
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from datetime import datetime
from typing import Any, Literal, Protocol, cast
from uuid import UUID, uuid4

from langgraph.graph import END, START, StateGraph

from app.agents.edges import after_intent, after_validation
from app.agents.llm import (
    GroqIntentModel,
    IntentBudgetExhausted,
    IntentModel,
    IntentModelFailure,
)
from app.agents.nodes.intent_node import build_intent_node
from app.agents.nodes.planning_node import build_planning_node
from app.agents.nodes.research_node import build_research_node
from app.agents.nodes.response_node import build_response_node
from app.agents.nodes.validation_node import validation_node
from app.agents.state import TravelState
from app.core.config import Settings
from app.core.rate_limiter import ExternalCallBudget
from app.core.security import utc_now
from app.core.tracing import ChatMode, graph_tracing_context
from app.integrations.base import ProviderBundle
from app.schemas.trip import TripResponse
from app.utils.datetime_utils import india_now

ProgressStage = Literal["intent", "research", "planning", "validation", "response"]
ProgressStatus = Literal["started", "completed", "degraded"]
ProgressCallback = Callable[[ProgressStage, ProgressStatus], Awaitable[None]]
_PROGRESS_CALLBACK: ContextVar[ProgressCallback | None] = ContextVar(
    "planning_progress_callback",
    default=None,
)


class TripPlanningFailure(Exception):
    """A user-safe planning boundary failure."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "trip_planning_unavailable",
        public_message: str = "Trip planning is temporarily unavailable. Please try again.",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.public_message = public_message


class TripPlanner(Protocol):
    async def run(
        self,
        *,
        conversation_id: UUID | None,
        user_prompt: str,
        previous_trip: TripResponse | None,
        chat_mode: ChatMode,
        trip_id: UUID | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> TripResponse: ...


def _progress_node(stage: ProgressStage, node: Callable[[TravelState], Any]) -> Any:
    async def wrapped(state: TravelState) -> dict[str, Any]:
        callback = _PROGRESS_CALLBACK.get()
        if callback is not None:
            await callback(stage, "started")
        result = cast(dict[str, Any], await node(state))
        status: ProgressStatus = "completed"
        if stage == "research" and any(
            getattr(source, "status", "ok") == "degraded"
            for source in result.get("provider_sources", [])
        ):
            status = "degraded"
        if callback is not None:
            await callback(stage, status)
        return result

    return wrapped


class LangGraphTripPlanner:
    def __init__(
        self,
        settings: Settings,
        *,
        intent_model: IntentModel | None = None,
        provider_factory: Callable[[datetime], ProviderBundle] = ProviderBundle.stubs,
        now_provider: Callable[[], datetime] = india_now,
        call_budget: ExternalCallBudget | None = None,
    ) -> None:
        self.settings = settings
        workflow = StateGraph(TravelState)
        workflow.add_node(
            "intent",
            _progress_node(
                "intent",
                build_intent_node(
                    intent_model or GroqIntentModel(settings, call_budget=call_budget),
                    now_provider=now_provider,
                ),
            ),
        )
        workflow.add_node(
            "research",
            _progress_node("research", build_research_node(provider_factory)),
        )
        workflow.add_node(
            "planning",
            _progress_node(
                "planning",
                build_planning_node(settings, now_provider=now_provider),
            ),
        )
        workflow.add_node("validation", _progress_node("validation", validation_node))
        workflow.add_node(
            "response",
            _progress_node("response", build_response_node(settings)),
        )
        workflow.add_edge(START, "intent")
        workflow.add_conditional_edges("intent", after_intent, {"research": "research", "end": END})
        workflow.add_edge("research", "planning")
        workflow.add_edge("planning", "validation")
        workflow.add_conditional_edges(
            "validation",
            after_validation,
            {"planning": "planning", "response": "response"},
        )
        workflow.add_edge("response", END)
        self.compiled = workflow.compile(name="devsafar-trip-planner")

    async def run(
        self,
        *,
        conversation_id: UUID | None,
        user_prompt: str,
        previous_trip: TripResponse | None,
        chat_mode: ChatMode,
        trip_id: UUID | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> TripResponse:
        fetched_at = utc_now()
        initial: TravelState = {
            "trip_id": trip_id or uuid4(),
            "conversation_id": conversation_id,
            "user_prompt": user_prompt,
            "requirements": None,
            "previous_trip": previous_trip,
            "route_options": [],
            "transport_options": [],
            "hotels": [],
            "attractions": [],
            "destination_knowledge": [],
            "itinerary": [],
            "budget_breakdown": None,
            "validation_errors": [],
            "feasible": None,
            "warnings": [],
            "retry_count": 0,
            "status": "completed",
            "provider_sources": [],
            "fetched_at": fetched_at,
            "final_response": None,
        }
        progress_token = _PROGRESS_CALLBACK.set(progress_callback)
        try:
            with graph_tracing_context(
                self.settings,
                chat_mode=chat_mode,
                conversation_id=conversation_id,
            ):
                async with asyncio.timeout(self.settings.graph_timeout_seconds):
                    output = cast(
                        TravelState,
                        await self.compiled.ainvoke(initial),
                    )
        except TimeoutError as exc:
            raise TripPlanningFailure(
                "Trip planning timed out",
                code="planning_timeout",
                public_message="Trip planning timed out. Please try again.",
            ) from exc
        except IntentBudgetExhausted as exc:
            raise TripPlanningFailure(
                "Groq intent budget exhausted",
                code="planning_intent_budget_exhausted",
                public_message="Trip planning capacity is unavailable right now. Please try later.",
            ) from exc
        except IntentModelFailure as exc:
            raise TripPlanningFailure("Trip intent extraction failed") from exc
        except Exception as exc:
            raise TripPlanningFailure("Trip planning failed") from exc
        finally:
            _PROGRESS_CALLBACK.reset(progress_token)
        response = output["final_response"]
        if response is None:
            raise TripPlanningFailure("Trip planning returned no response")
        return response
