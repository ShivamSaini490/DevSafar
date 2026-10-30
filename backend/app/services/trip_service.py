
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.security import utc_now
from app.repositories.itinerary_repository import ItineraryRepository
from app.repositories.trip_repository import TripRepository
from app.schemas.trip import TripResponse


class TripService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.trips = TripRepository(db)
        self.itineraries = ItineraryRepository(db)

    async def latest_response(self, conversation_id: UUID) -> TripResponse | None:
        trip = await self.trips.latest_for_conversation(conversation_id)
        return (
            TripResponse.model_validate(trip.response_json) if trip is not None else None
        )

    async def persist(
        self, *, conversation_id: UUID, response: TripResponse
    ) -> None:
        created_at = utc_now()
        payload = response.model_dump(mode="json")
        await self.trips.create(
            trip_id=response.trip_id,
            conversation_id=conversation_id,
            status=response.status,
            requirements=response.requirements.model_dump(mode="json"),
            response_json=payload,
            created_at=created_at,
        )
        await self.itineraries.create_next_version(
            trip_id=response.trip_id,
            conversation_id=conversation_id,
            itinerary_json=[
                day.model_dump(mode="json") for day in response.itinerary_days
            ],
            created_at=created_at,
        )

    async def get_owned_active(
        self, *, trip_id: UUID, owner_id: UUID
    ) -> TripResponse:
        trip = await self.trips.get_owned_active(
            trip_id=trip_id, owner_id=owner_id, now=utc_now()
        )
        if trip is None:
            raise AppError(404, "trip_not_found", "Trip not found.")
        return TripResponse.model_validate(trip.response_json)
