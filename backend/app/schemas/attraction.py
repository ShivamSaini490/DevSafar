
from app.schemas.common import PriceQuote, StrictSchema


class AttractionOption(StrictSchema):
    destination: str
    name: str
    description: str
    entry_fee: PriceQuote
    opening_hours: str | None = None
