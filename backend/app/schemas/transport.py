from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field

from app.schemas.common import PriceQuote, StrictSchema

TransportMode = Literal["flight", "train", "bus", "road", "unknown"]


class RouteLeg(StrictSchema):
    origin: str
    destination: str
    mode: TransportMode = "unknown"
    duration_minutes: int | None = Field(default=None, ge=0)
    duration_source: str | None = None
    distance_km: Decimal | None = Field(default=None, ge=0)
    departure_at: datetime | None = None
    arrival_at: datetime | None = None
    overnight_stops: int = Field(default=0, ge=0)
    price: PriceQuote


class TransportOption(StrictSchema):
    origin: str
    destination: str
    mode: TransportMode
    provider: str
    duration_minutes: int | None = Field(default=None, ge=0)
    price: PriceQuote
    availability: Literal["available", "unavailable", "unknown"] = "unknown"
