from datetime import datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.budget import BudgetBreakdown, BudgetCategory
from app.schemas.common import PriceQuote
from app.utils.currency_utils import sum_known_amounts
from app.utils.datetime_utils import INDIA_TIME_ZONE, as_india_time


def test_budget_categories_sum_exactly_with_decimal() -> None:
    fetched_at = datetime(2026, 10, 30, tzinfo=INDIA_TIME_ZONE)
    categories = [
        BudgetCategory(
            name="Transport",
            amount=Decimal("6000.25"),
            price_type="estimate",
            source="stub",
            fetched_at=fetched_at,
        ),
        BudgetCategory(
            name="Hotels",
            amount=Decimal("3999.75"),
            price_type="estimate",
            source="stub",
            fetched_at=fetched_at,
        ),
    ]
    budget = BudgetBreakdown(
        total_estimated=Decimal("10000.00"),
        price_type="estimate",
        categories=categories,
    )
    assert sum_known_amounts(item.amount for item in budget.categories) == (budget.total_estimated)
    assert budget.known_subtotal == Decimal("10000.00")
    assert budget.unknown_categories == []


def test_unknown_prices_are_null_and_cannot_be_zero() -> None:
    fetched_at = datetime(2026, 10, 30, tzinfo=INDIA_TIME_ZONE)
    quote = PriceQuote(
        amount=None,
        price_type="unknown",
        source="stub",
        fetched_at=fetched_at,
    )
    assert quote.amount is None
    with pytest.raises(ValidationError):
        PriceQuote(
            amount=Decimal("0"),
            price_type="unknown",
            source="stub",
            fetched_at=fetched_at,
        )


def test_naive_deadline_defaults_to_asia_kolkata() -> None:
    naive = datetime(2026, 11, 2, 10, 0)
    localized = as_india_time(naive)
    assert localized.utcoffset().total_seconds() == 19_800
