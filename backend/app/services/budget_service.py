from collections.abc import Sequence
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from app.core.security import utc_now
from app.schemas.attraction import AttractionOption
from app.schemas.budget import BudgetBreakdown, BudgetCategory
from app.schemas.hotel import HotelOption
from app.schemas.transport import RouteLeg, TransportOption
from app.schemas.trip import TripRequirements
from app.utils.currency_utils import all_amounts_known, sum_known_amounts


def _priced_category(
    *,
    name: str,
    amounts: Sequence[Decimal | None],
    fetched_at: datetime,
    source: str = "stub",
) -> BudgetCategory:
    if amounts and not all_amounts_known(amounts):
        return BudgetCategory(
            name=name,
            amount=None,
            price_type="unknown",
            source=source,
            fetched_at=fetched_at,
        )
    return BudgetCategory(
        name=name,
        amount=sum_known_amounts(amounts),
        price_type="estimate",
        source=source,
        fetched_at=fetched_at,
    )


class BudgetService:
    @staticmethod
    def build(
        *,
        requirements: TripRequirements,
        transport_options: list[TransportOption],
        hotels: list[HotelOption],
        attractions: list[AttractionOption],
        route_legs: list[RouteLeg] | None = None,
        food_per_day_per_traveler: Decimal | None = None,
        buffer_percent: Decimal | None = None,
    ) -> BudgetBreakdown:
        effective_route_legs = route_legs or []
        uses_osrm_road_cost = bool(effective_route_legs) and any(
            (item.duration_source or "").startswith("osrm") for item in effective_route_legs
        )
        if uses_osrm_road_cost:
            priced_transport = [item.price.amount for item in effective_route_legs]
            transport_source = "fuel_formula"
        else:
            priced_transport = [item.price.amount for item in transport_options]
            transport_source = "stub"
        priced_hotels = [item.total_price.amount for item in hotels]
        attraction_prices = [item.entry_fee.amount for item in attractions]
        fetched_at = next(
            iter(
                [item.price.fetched_at for item in effective_route_legs]
                + [item.price.fetched_at for item in transport_options]
                + [item.total_price.fetched_at for item in hotels]
                + [item.entry_fee.fetched_at for item in attractions]
            ),
            utc_now(),
        )
        categories = [
            _priced_category(
                name="Transport",
                amounts=priced_transport,
                fetched_at=fetched_at,
                source=transport_source,
            )
        ]
        if hotels:
            categories.append(
                _priced_category(
                    name="Hotels",
                    amounts=priced_hotels,
                    fetched_at=fetched_at,
                )
            )
        if attractions:
            known_attraction_prices = [amount for amount in attraction_prices if amount is not None]
            if known_attraction_prices:
                categories.append(
                    _priced_category(
                        name="Attractions",
                        amounts=known_attraction_prices,
                        fetched_at=fetched_at,
                        source="provider_sources",
                    )
                )
            if len(known_attraction_prices) != len(attraction_prices):
                categories.append(
                    _priced_category(
                        name=(
                            "Attractions"
                            if not known_attraction_prices
                            else "Attractions (unpriced entries)"
                        ),
                        amounts=[None],
                        fetched_at=fetched_at,
                        source="provider_sources",
                    )
                )

        if food_per_day_per_traveler is not None:
            trip_days = (
                (requirements.end_date - requirements.start_date).days + 1
                if requirements.start_date is not None and requirements.end_date is not None
                else 0
            )
            categories.append(
                BudgetCategory(
                    name="Food",
                    amount=(food_per_day_per_traveler * trip_days * requirements.travelers),
                    price_type="estimate",
                    source="configured_rule",
                    fetched_at=fetched_at,
                )
            )

        if buffer_percent is not None:
            subtotal_before_buffer = sum_known_amounts(category.amount for category in categories)
            categories.append(
                BudgetCategory(
                    name="Buffer",
                    amount=(subtotal_before_buffer * buffer_percent / Decimal("100")).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    ),
                    price_type="estimate",
                    source="configured_rule",
                    fetched_at=fetched_at,
                )
            )

        known_subtotal = sum_known_amounts(category.amount for category in categories)
        unknown_categories = [category.name for category in categories if category.amount is None]
        if unknown_categories:
            return BudgetBreakdown(
                total_estimated=None,
                known_subtotal=known_subtotal,
                unknown_categories=unknown_categories,
                price_type="unknown",
                categories=categories,
            )
        return BudgetBreakdown(
            total_estimated=known_subtotal,
            known_subtotal=known_subtotal,
            unknown_categories=[],
            price_type="estimate",
            categories=categories,
        )
