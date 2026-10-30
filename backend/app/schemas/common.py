
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

PriceType = Literal["live_quote", "estimate", "unknown"]
Currency = Literal["INR"]


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PriceQuote(StrictSchema):
    amount: Decimal | None = Field(default=None, ge=0)
    currency: Currency = "INR"
    price_type: PriceType
    source: str = Field(min_length=1, max_length=100)
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


class BookingLink(StrictSchema):
    provider: str = Field(min_length=1, max_length=100)
    url: HttpUrl
