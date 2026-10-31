
from datetime import datetime

from pydantic import HttpUrl

from app.schemas.common import PriceQuote, StrictSchema


class AttractionOption(StrictSchema):
    destination: str
    name: str
    description: str
    entry_fee: PriceQuote
    opening_hours: str | None = None
    source_url: HttpUrl | None = None
    source_domain: str | None = None
    fetched_at: datetime
