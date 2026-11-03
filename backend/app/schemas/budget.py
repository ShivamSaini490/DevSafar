from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field, model_validator

from app.schemas.common import Currency, PriceStatus, PriceType, StrictSchema


class BudgetCategory(StrictSchema):
    name: str
    amount: Decimal | None = Field(default=None, ge=0)
    amount_min: Decimal | None = Field(default=None, ge=0)
    amount_max: Decimal | None = Field(default=None, ge=0)
    price_type: PriceType
    source: str
    fetched_at: datetime
    status: PriceStatus = "formula_estimate"
    provider: str = "internal"
    observed_at: datetime | None = None
    price_unit: str = "trip total"
    sample_count: int | None = Field(default=None, ge=1)
    bookable: Literal[False] = False
    note: str | None = Field(default=None, min_length=1, max_length=300)

    @model_validator(mode="before")
    @classmethod
    def populate_legacy_provenance(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        price_type = payload.get("price_type", "unknown")
        payload.setdefault(
            "status",
            "unavailable" if price_type == "unknown" else "formula_estimate",
        )
        payload.setdefault("provider", payload.get("source") or "legacy")
        payload.setdefault("observed_at", payload.get("fetched_at"))
        payload.setdefault("price_unit", "trip total")
        payload.setdefault("bookable", False)
        return payload

    @model_validator(mode="after")
    def validate_amount(self) -> "BudgetCategory":
        range_present = self.amount_min is not None or self.amount_max is not None
        if range_present and (self.amount_min is None or self.amount_max is None):
            raise ValueError("Budget ranges require both amount_min and amount_max")
        if (
            self.amount_min is not None
            and self.amount_max is not None
            and self.amount_min > self.amount_max
        ):
            raise ValueError("amount_min cannot exceed amount_max")
        if self.price_type == "unknown":
            if self.amount is not None or range_present:
                raise ValueError("Unknown budget categories must keep amounts null")
            return self
        if self.amount is None and not range_present:
            raise ValueError("Known budget categories require an amount or range")
        if self.amount is not None and range_present:
            raise ValueError("Use either amount or an amount range, not both")
        return self


class BudgetBreakdown(StrictSchema):
    currency: Currency = "INR"
    total_estimated: Decimal | None = Field(default=None, ge=0)
    estimated_total_min: Decimal | None = Field(default=None, ge=0)
    estimated_total_max: Decimal | None = Field(default=None, ge=0)
    known_subtotal: Decimal = Field(default=Decimal("0"), ge=0)
    unknown_categories: list[str] = Field(default_factory=list)
    omitted_categories: list[str] = Field(default_factory=list)
    live_based_total: Decimal | None = Field(default=None, ge=0)
    estimate_based_total_min: Decimal | None = Field(default=None, ge=0)
    estimate_based_total_max: Decimal | None = Field(default=None, ge=0)
    mixed_confidence: bool = False
    price_type: PriceType
    categories: list[BudgetCategory] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def populate_legacy_summary_fields(cls, value: Any) -> Any:
        """Backfill fields absent from JSON persisted by migration 0003."""

        if not isinstance(value, dict):
            return value
        payload = dict(value)
        categories = payload.get("categories") or []
        if "known_subtotal" not in payload:
            payload["known_subtotal"] = sum(
                (
                    Decimal(
                        str(
                            (
                                category.amount
                                if category.amount is not None
                                else category.amount_min
                            )
                            if isinstance(category, BudgetCategory)
                            else (
                                category.get("amount")
                                if category.get("amount") is not None
                                else category.get("amount_min")
                            )
                        )
                    )
                    for category in categories
                    if (
                        isinstance(category, BudgetCategory)
                        and (category.amount is not None or category.amount_min is not None)
                    )
                    or (
                        isinstance(category, dict)
                        and (
                            category.get("amount") is not None
                            or category.get("amount_min") is not None
                        )
                    )
                ),
                Decimal("0"),
            )
        if "unknown_categories" not in payload:
            payload["unknown_categories"] = [
                (
                    category.name
                    if isinstance(category, BudgetCategory)
                    else str(category.get("name", "Unknown"))
                )
                for category in categories
                if (
                    isinstance(category, BudgetCategory)
                    and category.price_type == "unknown"
                )
                or (
                    isinstance(category, dict)
                    and category.get("price_type") == "unknown"
                )
            ]
        payload.setdefault("estimated_total_min", None)
        payload.setdefault("estimated_total_max", None)
        payload.setdefault("omitted_categories", payload.get("unknown_categories", []))
        payload.setdefault("live_based_total", None)
        payload.setdefault("estimate_based_total_min", None)
        payload.setdefault("estimate_based_total_max", None)
        payload.setdefault("mixed_confidence", False)
        return payload

    @model_validator(mode="after")
    def validate_total(self) -> "BudgetBreakdown":
        known_subtotal = sum(
            (
                category.amount
                if category.amount is not None
                else (category.amount_min or Decimal("0"))
                for category in self.categories
                if category.amount is not None or category.amount_min is not None
            ),
            Decimal("0"),
        )
        if self.known_subtotal != known_subtotal:
            raise ValueError("known_subtotal must equal known category amounts")
        expected_unknown = [
            category.name for category in self.categories if category.price_type == "unknown"
        ]
        if self.unknown_categories != expected_unknown:
            raise ValueError("unknown_categories must list categories with unknown amounts")
        if self.omitted_categories != expected_unknown:
            raise ValueError("omitted_categories must list unavailable categories")
        if not self.categories:
            if (
                self.total_estimated is not None
                or self.price_type != "unknown"
                or self.known_subtotal != 0
                or self.unknown_categories
            ):
                raise ValueError("An empty budget must be unknown")
            return self
        if (self.estimated_total_min is None) != (self.estimated_total_max is None):
            raise ValueError("Estimated totals require both minimum and maximum")
        if (
            self.estimated_total_min is not None
            and self.estimated_total_max is not None
            and self.estimated_total_min > self.estimated_total_max
        ):
            raise ValueError("estimated_total_min cannot exceed estimated_total_max")
        if self.estimated_total_min is not None:
            if self.total_estimated is not None or self.price_type != "estimate":
                raise ValueError("A budget range must use estimate with null total_estimated")
            return self
        amounts = [category.amount for category in self.categories]
        if any(amount is None for amount in amounts):
            if self.total_estimated is not None or self.price_type != "unknown":
                raise ValueError("Budget total must be unknown when a category is unknown")
            return self
        expected = sum((amount for amount in amounts if amount is not None), Decimal("0"))
        if self.total_estimated != expected:
            raise ValueError("Budget categories must sum to total_estimated")
        if self.price_type == "unknown":
            raise ValueError("Known budget totals cannot use unknown price_type")
        return self


def empty_budget() -> BudgetBreakdown:
    return BudgetBreakdown(
        total_estimated=None,
        estimated_total_min=None,
        estimated_total_max=None,
        known_subtotal=Decimal("0"),
        unknown_categories=[],
        price_type="unknown",
        categories=[],
    )
