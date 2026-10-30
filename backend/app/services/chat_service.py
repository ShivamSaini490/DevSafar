
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import PLACEHOLDER_ASSISTANT_REPLY
from app.core.security import utc_now
from app.models.message import Message
from app.repositories.message_repository import MessageRepository
from app.services.conversation_service import ConversationService


@dataclass(frozen=True, slots=True)
class SavedChatTurn:
    user_message: Message
    assistant_message: Message


class ChatService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.conversation_service = ConversationService(db)
        self.messages = MessageRepository(db)

    async def append_placeholder_turn(
        self, *, conversation_id: UUID, owner_id: UUID, content: str
    ) -> SavedChatTurn:
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
            content=PLACEHOLDER_ASSISTANT_REPLY,
            created_at=utc_now(),
        )
        await self.db.commit()
        await self.db.refresh(user_message)
        await self.db.refresh(assistant_message)
        return SavedChatTurn(user_message, assistant_message)

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
