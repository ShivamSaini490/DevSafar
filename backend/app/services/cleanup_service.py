
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import utc_now
from app.models.conversation import Conversation
from app.models.message import Message


@dataclass(frozen=True, slots=True)
class CleanupCounts:
    conversations: int = 0
    messages: int = 0


async def _delete_future_conversation_dependencies(
    _db: AsyncSession, _conversation_ids: list[UUID]
) -> None:
    """Hook for later trips, itineraries, and LangGraph checkpoint cleanup."""


class CleanupService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def delete_expired_conversations(
        self, *, batch_size: int, now: datetime | None = None
    ) -> CleanupCounts:
        cutoff = now or utc_now()
        conversation_count = 0
        message_count = 0
        while True:
            async with self.db.begin():
                ids = list(
                    (
                        await self.db.scalars(
                            select(Conversation.id)
                            .where(Conversation.expires_at <= cutoff)
                            .order_by(Conversation.expires_at.asc(), Conversation.id.asc())
                            .limit(batch_size)
                            .with_for_update(skip_locked=True)
                        )
                    ).all()
                )
                if not ids:
                    break
                batch_message_count = await self.db.scalar(
                    select(func.count(Message.id)).where(Message.conversation_id.in_(ids))
                )
                await _delete_future_conversation_dependencies(self.db, ids)
                await self.db.execute(delete(Message).where(Message.conversation_id.in_(ids)))
                result = cast(
                    CursorResult[Any],
                    await self.db.execute(
                        delete(Conversation).where(
                            Conversation.id.in_(ids), Conversation.expires_at <= cutoff
                        )
                    ),
                )
                conversation_count += int(result.rowcount or 0)
                message_count += int(batch_message_count or 0)
        return CleanupCounts(conversations=conversation_count, messages=message_count)
