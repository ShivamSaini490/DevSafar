
from datetime import date as Date
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

PriceType = Literal["live_quote", "estimate", "unknown"]
PriceStatus = Literal[
    "live_search_result",
    "previous",
    "estimated",
    "formula_estimate",
    "unavailable",
    "stale_snapshot",
]
Currency = Literal["INR"]


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PriceQuote(StrictSchema):
    amount: Decimal | None = Field(default=None, ge=0)
    amount_min: Decimal | None = Field(default=None, ge=0)
    amount_max: Decimal | None = Field(default=None, ge=0)
    currency: Currency = "INR"
    price_type: PriceType
    source: str = Field(min_length=1, max_length=2048)
    fetched_at: datetime
    status: PriceStatus
    provider: str = Field(min_length=1, max_length=100)
    observed_at: datetime
    price_unit: str = Field(min_length=1, max_length=100)
    sample_count: int | None = Field(default=None, ge=1)
    bookable: Literal[False] = False
    note: str | None = Field(default=None, min_length=1, max_length=300)

    @model_validator(mode="before")
    @classmethod
    def populate_backward_compatible_price_fields(cls, value: Any) -> Any:
        """Load JSON written before price status/provenance fields existed."""

        if not isinstance(value, dict):
            return value
        payload = dict(value)
        price_type = payload.get("price_type", "unknown")
        source = str(payload.get("source") or "legacy")
        status = payload.get("status")
        if status is None:
            if price_type == "live_quote":
                status = "live_search_result"
            elif price_type == "estimate":
                status = (
                    "formula_estimate"
                    if source in {
                        "configured_rule",
                        "distance_formula",
                        "fuel_formula",
                        "stub",
                        "tier_assumption",
                    }
                    else "estimated"
                )
            else:
                status = "unavailable"
        payload["status"] = status
        payload.setdefault("provider", source)
        payload.setdefault("observed_at", payload.get("fetched_at"))
        payload.setdefault("price_unit", "legacy price unit not recorded")
        payload.setdefault("bookable", False)
        if status == "estimated" and payload.get("sample_count") is None:
            # Legacy estimates did not record samples; classify them as formula estimates.
            payload["status"] = "formula_estimate"
        if payload["status"] == "live_search_result":
            disclaimer = "search result, not a confirmed booking"
            note = payload.get("note")
            if not note:
                payload["note"] = disclaimer
            elif disclaimer not in str(note).casefold():
                payload["note"] = f"{note}; {disclaimer}"
        return payload

    @model_validator(mode="after")
    def validate_price_provenance(self) -> "PriceQuote":
        range_present = self.amount_min is not None or self.amount_max is not None
        if range_present and (self.amount_min is None or self.amount_max is None):
            raise ValueError("Price ranges require both amount_min and amount_max")
        if (
            self.amount_min is not None
            and self.amount_max is not None
            and self.amount_min > self.amount_max
        ):
            raise ValueError("amount_min cannot exceed amount_max")
        if self.status == "unavailable":
            if self.price_type != "unknown":
                raise ValueError("Unavailable prices must use price_type unknown")
            if self.amount is not None or range_present:
                raise ValueError("Unavailable prices must keep all amounts null")
            return self
        if self.status == "live_search_result":
            if self.price_type != "live_quote" or self.amount is None or range_present:
                raise ValueError("Live search results require one live_quote amount")
            if "search result, not a confirmed booking" not in (self.note or "").casefold():
                raise ValueError("Live search results require the booking disclaimer")
        elif self.status in {"previous", "estimated", "formula_estimate"}:
            if self.price_type != "estimate":
                raise ValueError("Fallback prices must use price_type estimate")
        if self.status == "previous" and (self.amount is None or range_present):
            raise ValueError("Previous prices require one amount")
        if self.status == "estimated" and (
            self.amount is None or not range_present or (self.sample_count or 0) < 3
        ):
            raise ValueError("Estimated history requires median, range, and 3+ samples")
        if self.status == "formula_estimate" and self.sample_count is not None:
            raise ValueError("Formula estimates cannot claim a history sample count")
        if self.amount is None and not range_present:
            raise ValueError("Known prices require an amount or amount range")
        if self.amount is not None and range_present and self.status != "estimated":
            raise ValueError("Use either amount or an amount range, not both")
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
    providers_tried: list[str] = Field(default_factory=list)
    note: str | None = Field(default=None, min_length=1, max_length=300)


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
