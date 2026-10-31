from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import TripPlanner
from app.core.security import utc_now
from app.models.message import Message
from app.repositories.message_repository import MessageRepository
from app.schemas.trip import TripResponse
from app.services.conversation_service import ConversationService
from app.services.trip_service import TripService


@dataclass(frozen=True, slots=True)
class SavedChatTurn:
    user_message: Message
    assistant_message: Message
    trip: TripResponse


def summarize_trip(response: TripResponse) -> str:
    feasibility = (
        "yes" if response.feasible is True else "no" if response.feasible is False else "unknown"
    )
    if response.status == "needs_clarification":
        reason = "critical trip details are missing"
    elif response.feasible is False:
        reason = response.warnings[0] if response.warnings else "a current constraint is blocking the plan"
    elif response.feasible is None:
        reason_warning = next(
            (
                warning
                for warning in response.warnings
                if warning.startswith("Feasibility cannot be verified")
            ),
            "provider-backed timing or pricing is incomplete",
        )
        reason = reason_warning.partition(":")[2].strip() or reason_warning
    else:
        reason = "the verified schedule meets the current deadline and known constraints"

    known_cost = _format_inr(response.budget.known_subtotal)
    if response.requirements.budget is None:
        cost_sentence = f"Known cost is INR {known_cost}; no budget was specified."
    else:
        cost_sentence = (
            f"Known cost is INR {known_cost} against a budget of INR "
            f"{_format_inr(response.requirements.budget)}."
        )
    clean_reason = reason.rstrip(".?!").lower()
    return f"Feasibility: {feasibility}. Main reason: {clean_reason}. {cost_sentence}"


def _format_inr(value: Decimal) -> str:
    if value == value.to_integral_value():
        return f"{value:,.0f}"
    return f"{value:,.2f}"


class ChatService:
    def __init__(self, db: AsyncSession, planner: TripPlanner | None = None) -> None:
        self.db = db
        self.planner = planner
        self.conversation_service = ConversationService(db)
        self.messages = MessageRepository(db)
        self.trips = TripService(db)

    async def append_turn(
        self, *, conversation_id: UUID, owner_id: UUID, content: str
    ) -> SavedChatTurn:
        if self.planner is None:
            raise RuntimeError("Trip planner is required to append a chat turn")
        await self.conversation_service.get_required(
            conversation_id=conversation_id,
            owner_id=owner_id,
        )
        previous_trip = await self.trips.latest_response(conversation_id)
        await self.db.rollback()
        trip = await self.planner.run(
            conversation_id=conversation_id,
            user_prompt=content,
            previous_trip=previous_trip,
            chat_mode="saved",
        )
        conversation = await self.conversation_service.get_required(
            conversation_id=conversation_id,
            owner_id=owner_id,
            for_update=True,
        )
        user_message = await self.messages.create(
            conversation_id=conversation.id,
            role="user",
            content=content,
            created_at=utc_now(),
        )
        assistant_message = await self.messages.create(
            conversation_id=conversation.id,
            role="assistant",
            content=summarize_trip(trip),
            created_at=utc_now(),
        )
        await self.trips.persist(conversation_id=conversation.id, response=trip)
        await self.db.commit()
        await self.db.refresh(user_message)
        await self.db.refresh(assistant_message)
        return SavedChatTurn(user_message, assistant_message, trip)

    async def list_messages(
        self,
        *,
        conversation_id: UUID,
        owner_id: UUID,
        limit: int,
        offset: int,
    ) -> list[Message]:
        await self.conversation_service.get_required(
            conversation_id=conversation_id,
            owner_id=owner_id,
        )
        return await self.messages.list_for_owned_active_conversation(
            conversation_id=conversation_id,
            owner_id=owner_id,
            now=utc_now(),
            limit=limit,
            offset=offset,
        )
