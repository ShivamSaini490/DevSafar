from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from app.schemas.common import PriceQuote, StrictSchema

TransportMode = Literal["flight", "train", "bus", "road", "unknown"]


class DrivingSegment(StrictSchema):
    starts_at: datetime
    ends_at: datetime


class FlightSearchAlternative(StrictSchema):
    airline: str | None = None
    amount: Decimal = Field(gt=0)
    total_duration_minutes: int | None = Field(default=None, ge=0)
    stops: int = Field(default=0, ge=0)
    departure_time: str | None = None
    arrival_time: str | None = None
    note: str = "Provider display data from a search result, not a confirmed schedule."


class RouteLeg(StrictSchema):
    origin: str
    destination: str
    mode: TransportMode = "unknown"
    duration_minutes: int | None = Field(default=None, ge=0)
    duration_minutes_min: int | None = Field(default=None, ge=0)
    duration_minutes_max: int | None = Field(default=None, ge=0)
    duration_source: str | None = None
    distance_km: Decimal | None = Field(default=None, ge=0)
    great_circle_distance_km: Decimal | None = Field(default=None, ge=0)
    departure_at: datetime | None = None
    arrival_at: datetime | None = None
    overnight_stops: int = Field(default=0, ge=0)
    driving_segments: list[DrivingSegment] = Field(default_factory=list)
    price: PriceQuote

    @model_validator(mode="after")
    def validate_duration_range(self) -> "RouteLeg":
        _validate_duration_range(self.duration_minutes_min, self.duration_minutes_max)
        return self


class TransportOption(StrictSchema):
    origin: str
    destination: str
    mode: TransportMode
    provider: str
    duration_minutes: int | None = Field(default=None, ge=0)
    duration_minutes_min: int | None = Field(default=None, ge=0)
    duration_minutes_max: int | None = Field(default=None, ge=0)
    distance_km: Decimal | None = Field(default=None, ge=0)
    price: PriceQuote
    availability: Literal["available", "unavailable", "unknown"] = "unknown"
    note: str | None = Field(default=None, min_length=1, max_length=300)
    alternatives: list[FlightSearchAlternative] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_duration_range(self) -> "TransportOption":
        _validate_duration_range(self.duration_minutes_min, self.duration_minutes_max)
        return self


def _validate_duration_range(minimum: int | None, maximum: int | None) -> None:
    if (minimum is None) != (maximum is None):
        raise ValueError("Duration ranges require both minimum and maximum")
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ValueError("Minimum duration cannot exceed maximum duration")
