
from datetime import date, datetime

from pydantic import Field

from app.schemas.common import StrictSchema


class ItineraryActivity(StrictSchema):
    title: str
    location: str
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    notes: str | None = None


class ItineraryDay(StrictSchema):
    day: int = Field(ge=1)
    date: date
    destination: str
    activities: list[ItineraryActivity] = Field(default_factory=list)
