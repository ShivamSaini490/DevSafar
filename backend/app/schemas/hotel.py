
from datetime import date
from typing import Literal

from app.schemas.common import PriceQuote, StrictSchema


class HotelOption(StrictSchema):
    destination: str
    name: str
    check_in: date
    check_out: date
    nightly_price: PriceQuote
    total_price: PriceQuote
    availability: str = "unknown"
    tier: Literal["budget", "standard", "comfort"] | None = None
    note: str | None = None
