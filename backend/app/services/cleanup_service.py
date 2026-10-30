
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import utc_now
from app.models.conversation import Conversation
from app.models.itinerary import Itinerary
from app.models.message import Message
from app.models.trip import Trip


@dataclass(frozen=True, slots=True)
class CleanupCounts:
    conversations: int = 0
    messages: int = 0
    trips: int = 0
    itineraries: int = 0


async def _delete_trip_and_itinerary_dependencies(
    db: AsyncSession, conversation_ids: list[UUID]
) -> tuple[int, int]:
    """Delete current graph artifacts; checkpoint deletion remains a later hook."""
    itinerary_count = await db.scalar(
        select(func.count(Itinerary.id)).where(
            Itinerary.conversation_id.in_(conversation_ids)
        )
    )
    trip_count = await db.scalar(
        select(func.count(Trip.id)).where(Trip.conversation_id.in_(conversation_ids))
    )
    await db.execute(
        delete(Itinerary).where(Itinerary.conversation_id.in_(conversation_ids))
    )
    await db.execute(delete(Trip).where(Trip.conversation_id.in_(conversation_ids)))
    return int(trip_count or 0), int(itinerary_count or 0)


async def _delete_future_langgraph_checkpoints(
    _db: AsyncSession, _conversation_ids: list[UUID]
) -> None:
    """Named hook for the deferred saved-chat checkpointer implementation."""


class CleanupService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def delete_expired_conversations(
        self, *, batch_size: int, now: datetime | None = None
    ) -> CleanupCounts:
        cutoff = now or utc_now()
        conversation_count = 0
        message_count = 0
        trip_count = 0
        itinerary_count = 0
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
                batch_trips, batch_itineraries = (
                    await _delete_trip_and_itinerary_dependencies(self.db, ids)
                )
                await _delete_future_langgraph_checkpoints(self.db, ids)
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
                trip_count += batch_trips
                itinerary_count += batch_itineraries
        return CleanupCounts(
            conversations=conversation_count,
            messages=message_count,
            trips=trip_count,
            itineraries=itinerary_count,
        )
