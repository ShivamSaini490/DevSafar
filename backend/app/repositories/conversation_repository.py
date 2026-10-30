
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        owner_id: UUID,
        title: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> Conversation:
        conversation = Conversation(
            owner_id=owner_id,
            title=title,
            created_at=created_at,
            expires_at=expires_at,
        )
        self.session.add(conversation)
        await self.session.flush()
        return conversation

    async def list_active(
        self,
        *,
        owner_id: UUID,
        now: datetime,
        limit: int,
        offset: int,
    ) -> list[Conversation]:
        statement = (
            select(Conversation)
            .where(
                Conversation.owner_id == owner_id,
                Conversation.expires_at > now,
            )
            .order_by(Conversation.created_at.desc(), Conversation.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list((await self.session.scalars(statement)).all())

    async def get_active(
        self,
        *,
        conversation_id: UUID,
        owner_id: UUID,
        now: datetime,
        for_update: bool = False,
    ) -> Conversation | None:
        statement = select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.owner_id == owner_id,
            Conversation.expires_at > now,
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def delete(self, conversation: Conversation) -> None:
        await self.session.delete(conversation)
