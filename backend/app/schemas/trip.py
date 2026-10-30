from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from app.schemas.attraction import AttractionOption
from app.schemas.budget import BudgetBreakdown
from app.schemas.common import BookingLink, DataSource, StrictSchema
from app.schemas.hotel import HotelOption
from app.schemas.itinerary import ItineraryDay
from app.schemas.transport import RouteLeg, TransportOption
from app.utils.datetime_utils import INDIA_TIME_ZONE

TripStatus = Literal["needs_clarification", "completed", "failed"]


def canonical_place_name(value: str) -> str:
    cleaned = " ".join(value.split())
    if cleaned.casefold() == "pondicherry":
        return "Puducherry"
    return cleaned


class TripRequirements(StrictSchema):
    origin: str | None = None
    destinations: list[str] = Field(default_factory=list)
    start_date: date | None = None
    end_date: date | None = None
    travelers: int = Field(default=1, ge=1, le=20)
    budget: Decimal | None = Field(default=None, ge=0)
    return_deadline: datetime | None = None
    preferences: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)

    @field_validator("origin")
    @classmethod
    def normalize_origin(cls, value: str | None) -> str | None:
        return canonical_place_name(value) if value is not None else None

    @field_validator("destinations")
    @classmethod
    def normalize_destinations(cls, values: list[str]) -> list[str]:
        return [canonical_place_name(value) for value in values]

    @field_validator("return_deadline")
    @classmethod
    def normalize_deadline(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=INDIA_TIME_ZONE)
        return value


class TripResponse(StrictSchema):
    trip_id: UUID
    status: TripStatus = Field(
        description=(
            "completed includes feasible and infeasible plans; failed is reserved for "
            "execution errors"
        )
    )
    requirements: TripRequirements
    feasible: bool | None
    warnings: list[str] = Field(default_factory=list)
    route_legs: list[RouteLeg] = Field(default_factory=list)
    transport_options: list[TransportOption] = Field(default_factory=list)
    hotels: list[HotelOption] = Field(default_factory=list)
    attractions: list[AttractionOption] = Field(default_factory=list)
    itinerary_days: list[ItineraryDay] = Field(default_factory=list)
    budget: BudgetBreakdown
    data_sources: list[DataSource] = Field(default_factory=list)
    booking_links: list[BookingLink] = Field(default_factory=list)
