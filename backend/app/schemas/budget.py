
from datetime import datetime
from decimal import Decimal

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
    price_type: PriceType
    categories: list[BudgetCategory] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_total(self) -> "BudgetBreakdown":
        if not self.categories:
            if self.total_estimated is not None or self.price_type != "unknown":
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
        price_type="unknown",
        categories=[],
    )
