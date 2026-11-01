
from datetime import date as Date
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

PriceType = Literal["live_quote", "estimate", "unknown"]
Currency = Literal["INR"]


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PriceQuote(StrictSchema):
    amount: Decimal | None = Field(default=None, ge=0)
    currency: Currency = "INR"
    price_type: PriceType
    source: str = Field(min_length=1, max_length=2048)
    fetched_at: datetime

    @model_validator(mode="after")
    def validate_price_provenance(self) -> "PriceQuote":
        if self.price_type == "unknown" and self.amount is not None:
            raise ValueError("Unknown prices must use null amount")
        if self.price_type != "unknown" and self.amount is None:
            raise ValueError("Known prices require an amount")
        return self


class DataSource(StrictSchema):
    name: str = Field(min_length=1, max_length=100)
    price_type: PriceType
    fetched_at: datetime
    updated_at: Date | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    status: Literal["ok", "degraded"] = "ok"


class BookingLink(StrictSchema):
    provider: str = Field(min_length=1, max_length=100)
    mode: Literal["train", "bus", "flight", "hotel"]
    label: str = Field(min_length=1, max_length=200)
    url: HttpUrl
    origin: str | None = Field(default=None, min_length=1, max_length=200)
    destination: str = Field(min_length=1, max_length=200)
    date: Date
    leg_index: int | None = Field(default=None, ge=0)
    stay_index: int | None = Field(default=None, ge=0)
    check_in: Date | None = None
    check_out: Date | None = None
    link_type: Literal["search_page"] = "search_page"
    price_known: Literal[False] = False
    note: str = Field(
        default="Opening a provider page is not a confirmed booking.",
        min_length=1,
        max_length=300,
    )

    @field_validator("note")
    @classmethod
    def require_booking_disclaimer(cls, value: str) -> str:
        if "Opening a provider page is not a confirmed booking." not in value:
            raise ValueError("Booking links must retain the unconfirmed-booking notice")
        return value
