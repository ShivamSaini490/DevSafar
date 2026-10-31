from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from app.schemas.attraction import AttractionOption
from app.schemas.budget import BudgetBreakdown
from app.schemas.common import PriceQuote
from app.schemas.trip import TripRequirements, TripResponse
from app.services.budget_service import BudgetService
from app.utils.datetime_utils import INDIA_TIME_ZONE


def test_food_and_buffer_are_omitted_without_configured_rules() -> None:
    requirements = TripRequirements(
        origin="Hyderabad",
        destinations=["Puducherry"],
        start_date=date(2026, 10, 30),
        end_date=date(2026, 11, 1),
        travelers=2,
    )

    budget = BudgetService.build(
        requirements=requirements,
        transport_options=[],
        hotels=[],
        attractions=[],
    )

    assert [category.name for category in budget.categories] == ["Transport", "Hotels"]
    assert budget.known_subtotal == 0
    assert budget.unknown_categories == []


def test_configured_food_and_buffer_rules_are_labelled_estimates() -> None:
    requirements = TripRequirements(
        origin="Hyderabad",
        destinations=["Puducherry"],
        start_date=date(2026, 10, 30),
        end_date=date(2026, 11, 1),
        travelers=2,
    )

    budget = BudgetService.build(
        requirements=requirements,
        transport_options=[],
        hotels=[],
        attractions=[],
        food_per_day_per_traveler=Decimal("500"),
        buffer_percent=Decimal("10"),
    )

    food = next(category for category in budget.categories if category.name == "Food")
    buffer = next(category for category in budget.categories if category.name == "Buffer")
    assert food.amount == Decimal("3000")
    assert buffer.amount == Decimal("300.00")
    assert food.source == buffer.source == "configured_rule"
    assert food.price_type == buffer.price_type == "estimate"
    assert budget.known_subtotal == Decimal("3300.00")
    assert budget.total_estimated == Decimal("3300.00")


def test_known_attraction_fees_feed_subtotal_while_unknown_fee_stays_unknown() -> None:
    fetched_at = datetime(2026, 10, 30, tzinfo=INDIA_TIME_ZONE)
    requirements = TripRequirements(
        origin="Hyderabad",
        destinations=["Vijayawada"],
        start_date=date(2026, 10, 30),
        end_date=date(2026, 11, 1),
    )
    attractions = [
        AttractionOption(
            destination="Vijayawada",
            name="Known fee attraction",
            description="Provider text",
            entry_fee=PriceQuote(
                amount=Decimal("250"),
                price_type="estimate",
                source="https://example.com/known",
                fetched_at=fetched_at,
            ),
            source_url="https://example.com/known",
            source_domain="example.com",
            fetched_at=fetched_at,
        ),
        AttractionOption(
            destination="Vijayawada",
            name="Unknown fee attraction",
            description="Provider text without a numeric fee",
            entry_fee=PriceQuote(
                amount=None,
                price_type="unknown",
                source="https://example.com/unknown",
                fetched_at=fetched_at,
            ),
            source_url="https://example.com/unknown",
            source_domain="example.com",
            fetched_at=fetched_at,
        ),
    ]

    budget = BudgetService.build(
        requirements=requirements,
        transport_options=[],
        hotels=[],
        attractions=attractions,
    )

    attraction_category = next(
        category for category in budget.categories if category.name == "Attractions"
    )
    assert attraction_category.amount == Decimal("250")
    assert budget.known_subtotal == Decimal("250")
    assert budget.total_estimated is None
    assert "Attractions (unpriced entries)" in budget.unknown_categories


def test_migration_0003_json_without_new_summary_fields_still_loads() -> None:
    fetched_at = datetime(2026, 10, 30, tzinfo=INDIA_TIME_ZONE)
    legacy_budget = {
        "currency": "INR",
        "total_estimated": "10000.00",
        "price_type": "estimate",
        "categories": [
            {
                "name": "Transport",
                "amount": "6000.00",
                "price_type": "estimate",
                "source": "stub",
                "fetched_at": fetched_at.isoformat(),
            },
            {
                "name": "Hotels",
                "amount": "4000.00",
                "price_type": "estimate",
                "source": "stub",
                "fetched_at": fetched_at.isoformat(),
            },
        ],
    }
    payload = {
        "trip_id": str(uuid4()),
        "status": "completed",
        "requirements": {
            "origin": "Hyderabad",
            "destinations": ["Puducherry"],
            "start_date": "2026-10-30",
            "end_date": "2026-11-01",
            "travelers": 1,
            "budget": "15000",
            "return_deadline": "2026-11-02T10:00:00+05:30",
            "preferences": [],
            "ambiguities": [],
        },
        "feasible": True,
        "warnings": [],
        "route_legs": [
            {
                "origin": "Hyderabad",
                "destination": "Puducherry",
                "mode": "unknown",
                "duration_minutes": 480,
                "distance_km": None,
                "departure_at": None,
                "arrival_at": None,
                "price": {
                    "amount": None,
                    "currency": "INR",
                    "price_type": "unknown",
                    "source": "stub",
                    "fetched_at": fetched_at.isoformat(),
                },
            }
        ],
        "transport_options": [],
        "hotels": [],
        "attractions": [],
        "itinerary_days": [],
        "budget": legacy_budget,
        "data_sources": [],
        "booking_links": [],
    }

    response = TripResponse.model_validate(payload)

    assert response.feasible is True
    assert response.route_legs[0].duration_source is None
    assert response.budget.known_subtotal == Decimal("10000.00")
    assert response.budget.unknown_categories == []
    assert BudgetBreakdown.model_validate(legacy_budget).total_estimated == Decimal("10000.00")
