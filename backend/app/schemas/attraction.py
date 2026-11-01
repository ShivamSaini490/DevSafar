
from datetime import datetime
from typing import Literal

from pydantic import Field, HttpUrl

from app.schemas.common import PriceQuote, StrictSchema

AttractionCategory = Literal[
    "beach",
    "temple",
    "museum",
    "fort",
    "church",
    "mosque",
    "monument",
    "heritage_site",
    "park",
    "garden",
    "nature",
    "island",
    "lake",
    "waterfall",
    "viewpoint",
    "market",
    "palace",
    "memorial",
    "bridge",
    "ashram",
    "aquarium",
    "zoo",
    "other_named_place",
]

ATTRACTION_CATEGORIES = (
    "beach",
    "temple",
    "museum",
    "fort",
    "church",
    "mosque",
    "monument",
    "heritage_site",
    "park",
    "garden",
    "nature",
    "island",
    "lake",
    "waterfall",
    "viewpoint",
    "market",
    "palace",
    "memorial",
    "bridge",
    "ashram",
    "aquarium",
    "zoo",
    "other_named_place",
)


class AttractionCandidate(StrictSchema):
    name: str = Field(min_length=2, max_length=120)
    category: AttractionCategory
    evidence_quote: str = Field(min_length=2, max_length=1000)


class AttractionExtractionCandidate(StrictSchema):
    name: str = Field(min_length=2, max_length=120)
    evidence_quote: str = Field(min_length=2, max_length=160)


class AttractionExtraction(StrictSchema):
    attractions: list[AttractionExtractionCandidate]


class AttractionOption(StrictSchema):
    destination: str
    name: str = Field(min_length=2, max_length=120)
    category: AttractionCategory | None = None
    description: str = Field(min_length=1, max_length=200)
    entry_fee: PriceQuote
    opening_hours: str | None = None
    source_url: HttpUrl | None = None
    additional_source_urls: list[HttpUrl] = Field(default_factory=list, max_length=2)
    source_domain: str | None = None
    fetched_at: datetime
