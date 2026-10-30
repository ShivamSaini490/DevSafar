from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import Field, model_validator

from app.schemas.common import Currency, PriceType, StrictSchema


class BudgetCategory(StrictSchema):
    name: str
    amount: Decimal | None = Field(default=None, ge=0)
    price_type: PriceType
    source: str
    fetched_at: datetime

    @model_validator(mode="after")
    def validate_amount(self) -> "BudgetCategory":
        if self.price_type == "unknown" and self.amount is not None:
            raise ValueError("Unknown budget categories must use null amount")
        if self.price_type != "unknown" and self.amount is None:
            raise ValueError("Known budget categories require an amount")
        return self


class BudgetBreakdown(StrictSchema):
    currency: Currency = "INR"
    total_estimated: Decimal | None = Field(default=None, ge=0)
    known_subtotal: Decimal = Field(default=Decimal("0"), ge=0)
    unknown_categories: list[str] = Field(default_factory=list)
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
                            category.amount
                            if isinstance(category, BudgetCategory)
                            else category["amount"]
                        )
                    )
                    for category in categories
                    if (isinstance(category, BudgetCategory) and category.amount is not None)
                    or (isinstance(category, dict) and category.get("amount") is not None)
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
                if (isinstance(category, BudgetCategory) and category.amount is None)
                or (isinstance(category, dict) and category.get("amount") is None)
            ]
        return payload

    @model_validator(mode="after")
    def validate_total(self) -> "BudgetBreakdown":
        known_subtotal = sum(
            (category.amount for category in self.categories if category.amount is not None),
            Decimal("0"),
        )
        if self.known_subtotal != known_subtotal:
            raise ValueError("known_subtotal must equal known category amounts")
        expected_unknown = [
            category.name for category in self.categories if category.amount is None
        ]
        if self.unknown_categories != expected_unknown:
            raise ValueError("unknown_categories must list categories with unknown amounts")
        if not self.categories:
            if (
                self.total_estimated is not None
                or self.price_type != "unknown"
                or self.known_subtotal != 0
                or self.unknown_categories
            ):
                raise ValueError("An empty budget must be unknown")
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
        known_subtotal=Decimal("0"),
        unknown_categories=[],
        price_type="unknown",
        categories=[],
    )
