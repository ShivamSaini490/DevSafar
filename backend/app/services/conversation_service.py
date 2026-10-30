
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import SAVED_CONVERSATION_TTL
from app.core.exceptions import AppError
from app.core.security import utc_now
from app.models.conversation import Conversation
from app.repositories.conversation_repository import ConversationRepository


class ConversationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.conversations = ConversationRepository(db)

    async def create(self, *, owner_id: UUID, title: str) -> Conversation:
        created_at = utc_now()
        conversation = await self.conversations.create(
            owner_id=owner_id,
            title=title,
            created_at=created_at,
            expires_at=created_at + SAVED_CONVERSATION_TTL,
        )
        await self.db.commit()
        await self.db.refresh(conversation)
        return conversation

    async def list_active(
        self, *, owner_id: UUID, limit: int, offset: int
    ) -> list[Conversation]:
        return await self.conversations.list_active(
            owner_id=owner_id,
            now=utc_now(),
            limit=limit,
            offset=offset,
        )

    async def get_required(
        self, *, conversation_id: UUID, owner_id: UUID, for_update: bool = False
    ) -> Conversation:
        conversation = await self.conversations.get_active(
            conversation_id=conversation_id,
            owner_id=owner_id,
            now=utc_now(),
            for_update=for_update,
        )
        if conversation is None:
            raise AppError(404, "conversation_not_found", "Conversation not found.")
        return conversation

    async def rename(
        self, *, conversation_id: UUID, owner_id: UUID, title: str
    ) -> Conversation:
        conversation = await self.get_required(
            conversation_id=conversation_id, owner_id=owner_id, for_update=True
        )
        conversation.title = title
        await self.db.commit()
        await self.db.refresh(conversation)
        return conversation

    async def delete(self, *, conversation_id: UUID, owner_id: UUID) -> None:
        conversation = await self.get_required(
            conversation_id=conversation_id, owner_id=owner_id, for_update=True
        )
        await self.conversations.delete(conversation)
        await self.db.commit()
