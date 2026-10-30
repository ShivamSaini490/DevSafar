
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.models.message import Message


class MessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        conversation_id: UUID,
        role: str,
        content: str,
        created_at: datetime,
    ) -> Message:
        message = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            created_at=created_at,
        )
        self.session.add(message)
        await self.session.flush()
        return message

    async def list_for_owned_active_conversation(
        self,
        *,
        conversation_id: UUID,
        owner_id: UUID,
        now: datetime,
        limit: int,
        offset: int,
    ) -> list[Message]:
        statement = (
            select(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Message.conversation_id == conversation_id,
                Conversation.owner_id == owner_id,
                Conversation.expires_at > now,
            )
            .order_by(Message.created_at.asc(), Message.id.asc())
            .limit(limit)
            .offset(offset)
        )
        return list((await self.session.scalars(statement)).all())
