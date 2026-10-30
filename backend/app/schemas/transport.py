
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
    distance_km: Decimal | None = Field(default=None, ge=0)
    departure_at: datetime | None = None
    arrival_at: datetime | None = None
    price: PriceQuote


class TransportOption(StrictSchema):
    origin: str
    destination: str
    mode: TransportMode
    provider: str
    duration_minutes: int | None = Field(default=None, ge=0)
    price: PriceQuote
    availability: Literal["available", "unavailable", "unknown"] = "unknown"
