from dataclasses import dataclass
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
    if response.status == "needs_clarification":
        return "I need a few details before planning: " + " ".join(response.warnings)
    if response.feasible is True:
        return "A source-labelled draft trip plan is ready. Verify unknown prices before booking."
    if response.feasible is None:
        return (
            "A source-labelled draft trip plan is ready. "
            "Feasibility cannot yet be verified. "
            + " ".join(response.warnings)
        )
    return "This plan is not feasible with the current constraints. " + " ".join(response.warnings)


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
