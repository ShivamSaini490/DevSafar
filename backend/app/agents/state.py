from datetime import datetime
from typing import TypedDict
from uuid import UUID

from app.schemas.attraction import AttractionOption
from app.schemas.budget import BudgetBreakdown
from app.schemas.common import DataSource
from app.schemas.hotel import HotelOption
from app.schemas.itinerary import ItineraryDay
from app.schemas.transport import RouteLeg, TransportOption
from app.schemas.trip import TripRequirements, TripResponse, TripStatus


class TravelState(TypedDict):
    conversation_id: UUID | None
    user_prompt: str
    requirements: TripRequirements | None
    previous_trip: TripResponse | None
    route_options: list[RouteLeg]
    transport_options: list[TransportOption]
    hotels: list[HotelOption]
    attractions: list[AttractionOption]
    destination_knowledge: list[str]
    itinerary: list[ItineraryDay]
    budget_breakdown: BudgetBreakdown | None
    validation_errors: list[str]
    feasible: bool | None
    warnings: list[str]
    retry_count: int
    status: TripStatus
    provider_sources: list[DataSource]
    fetched_at: datetime | None
    final_response: TripResponse | None
