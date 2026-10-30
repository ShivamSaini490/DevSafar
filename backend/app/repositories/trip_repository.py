
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.models.trip import Trip


class TripRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        trip_id: UUID,
        conversation_id: UUID,
        status: str,
        requirements: dict[str, Any],
        response_json: dict[str, Any],
        created_at: datetime,
    ) -> Trip:
        trip = Trip(
            id=trip_id,
            conversation_id=conversation_id,
            status=status,
            requirements=requirements,
            response_json=response_json,
            created_at=created_at,
        )
        self.session.add(trip)
        await self.session.flush()
        return trip

    async def latest_for_conversation(self, conversation_id: UUID) -> Trip | None:
        return await self.session.scalar(
            select(Trip)
            .where(Trip.conversation_id == conversation_id)
            .order_by(Trip.created_at.desc(), Trip.id.desc())
            .limit(1)
        )

    async def get_owned_active(
        self, *, trip_id: UUID, owner_id: UUID, now: datetime
    ) -> Trip | None:
        return await self.session.scalar(
            select(Trip)
            .join(Conversation, Conversation.id == Trip.conversation_id)
            .where(
                Trip.id == trip_id,
                Conversation.owner_id == owner_id,
                Conversation.expires_at > now,
            )
        )
