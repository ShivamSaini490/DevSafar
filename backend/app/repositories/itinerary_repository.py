
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.itinerary import Itinerary


class ItineraryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_next_version(
        self,
        *,
        trip_id: UUID,
        conversation_id: UUID,
        itinerary_json: list[dict[str, Any]],
        created_at: datetime,
    ) -> Itinerary:
        current_version = await self.session.scalar(
            select(func.coalesce(func.max(Itinerary.version), 0)).where(
                Itinerary.conversation_id == conversation_id
            )
        )
        itinerary = Itinerary(
            trip_id=trip_id,
            conversation_id=conversation_id,
            version=int(current_version or 0) + 1,
            itinerary_json=itinerary_json,
            created_at=created_at,
        )
        self.session.add(itinerary)
        await self.session.flush()
        return itinerary
