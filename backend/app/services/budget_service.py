from collections.abc import Sequence
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from app.core.security import utc_now
from app.schemas.attraction import AttractionOption
from app.schemas.budget import BudgetBreakdown, BudgetCategory
from app.schemas.hotel import HotelOption
from app.schemas.transport import RouteLeg, TransportOption
from app.schemas.trip import ModeComparison, TripRequirements
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
    def build_estimated_range(
        *,
        comparison: ModeComparison | None,
        hotel_total_min: Decimal,
        hotel_total_max: Decimal,
        food_total_min: Decimal,
        food_total_max: Decimal,
        local_transport_total_min: Decimal,
        local_transport_total_max: Decimal,
        attractions: list[AttractionOption],
        fetched_at: datetime,
    ) -> BudgetBreakdown:
        categories: list[BudgetCategory] = []
        transport_min, transport_max = (
            _price_bounds(comparison.transport_price)
            if comparison is not None
            else (None, None)
        )
        if transport_min is None or transport_max is None:
            categories.append(
                BudgetCategory(
                    name="Transport",
                    amount=None,
                    price_type="unknown",
                    source="distance_formula",
                    fetched_at=fetched_at,
                    status="unavailable",
                    provider="price_engine",
                    observed_at=fetched_at,
                    price_unit="trip transport total",
                )
            )
        else:
            categories.append(
                BudgetCategory(
                    name="Transport",
                    amount_min=transport_min,
                    amount_max=transport_max,
                    price_type=(
                        "live_quote"
                        if comparison is not None
                        and comparison.transport_price.status == "live_search_result"
                        else "estimate"
                    ),
                    source=(
                        comparison.transport_price.source
                        if comparison is not None
                        else "distance_formula"
                    ),
                    fetched_at=fetched_at,
                    status=(
                        comparison.transport_price.status
                        if comparison is not None
                        else "formula_estimate"
                    ),
                    provider=(
                        comparison.transport_price.provider
                        if comparison is not None
                        else "distance_formula"
                    ),
                    observed_at=(
                        comparison.transport_price.observed_at
                        if comparison is not None
                        else fetched_at
                    ),
                    price_unit="trip transport total",
                    note=(comparison.transport_price.note if comparison is not None else None),
                )
            )
        categories.extend(
            [
                BudgetCategory(
                    name="Hotels",
                    amount_min=hotel_total_min,
                    amount_max=hotel_total_max,
                    price_type="estimate",
                    source="tier_assumption",
                    fetched_at=fetched_at,
                ),
                BudgetCategory(
                    name="Food",
                    amount_min=food_total_min,
                    amount_max=food_total_max,
                    price_type="estimate",
                    source="configured_rule",
                    fetched_at=fetched_at,
                ),
                BudgetCategory(
                    name="Local transport",
                    amount_min=local_transport_total_min,
                    amount_max=local_transport_total_max,
                    price_type="estimate",
                    source="configured_rule",
                    fetched_at=fetched_at,
                ),
            ]
        )
        known_attraction_amounts = [
            item.entry_fee.amount
            for item in attractions
            if item.entry_fee.amount is not None
        ]
        known_attraction_total = sum_known_amounts(known_attraction_amounts)
        if known_attraction_amounts:
            categories.append(
                BudgetCategory(
                    name="Attractions",
                    amount=known_attraction_total,
                    price_type="estimate",
                    source="provider_sources",
                    fetched_at=fetched_at,
                )
            )
        if len(known_attraction_amounts) != len(attractions):
            categories.append(
                BudgetCategory(
                    name=(
                        "Attractions"
                        if not known_attraction_amounts
                        else "Attractions (unpriced entries)"
                    ),
                    amount=None,
                    price_type="unknown",
                    source="provider_sources",
                    fetched_at=fetched_at,
                )
            )
        known_subtotal = sum_known_amounts(
            category.amount if category.amount is not None else category.amount_min
            for category in categories
        )
        unknown_categories = [
            category.name for category in categories if category.price_type == "unknown"
        ]
        numeric = [
            (category.amount, category.amount)
            if category.amount is not None
            else (category.amount_min, category.amount_max)
            for category in categories
            if category.amount is not None
            or (category.amount_min is not None and category.amount_max is not None)
        ]
        estimated_min = sum((item[0] or Decimal("0") for item in numeric), Decimal("0")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        estimated_max = sum((item[1] or Decimal("0") for item in numeric), Decimal("0")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        live_numeric = [
            (category.amount, category.amount)
            if category.amount is not None
            else (category.amount_min, category.amount_max)
            for category in categories
            if category.status == "live_search_result"
            and (
                category.amount is not None
                or (category.amount_min is not None and category.amount_max is not None)
            )
        ]
        estimate_numeric = [
            (category.amount, category.amount)
            if category.amount is not None
            else (category.amount_min, category.amount_max)
            for category in categories
            if category.status in {"previous", "estimated", "formula_estimate"}
            and (
                category.amount is not None
                or (category.amount_min is not None and category.amount_max is not None)
            )
        ]
        live_total = sum(
            (item[0] or Decimal("0") for item in live_numeric), Decimal("0")
        )
        estimate_min = sum(
            (item[0] or Decimal("0") for item in estimate_numeric), Decimal("0")
        )
        estimate_max = sum(
            (item[1] or Decimal("0") for item in estimate_numeric), Decimal("0")
        )
        has_live = any(category.status == "live_search_result" for category in categories)
        has_estimate = any(
            category.status in {"previous", "estimated", "formula_estimate"}
            for category in categories
        )
        return BudgetBreakdown(
            total_estimated=None,
            estimated_total_min=estimated_min if numeric else None,
            estimated_total_max=estimated_max if numeric else None,
            known_subtotal=known_subtotal,
            unknown_categories=unknown_categories,
            omitted_categories=unknown_categories,
            live_based_total=live_total if has_live else None,
            estimate_based_total_min=estimate_min if has_estimate else None,
            estimate_based_total_max=estimate_max if has_estimate else None,
            mixed_confidence=has_live and has_estimate,
            price_type="estimate" if numeric else "unknown",
            categories=categories,
        )

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
                omitted_categories=unknown_categories,
                price_type="unknown",
                categories=categories,
            )
        return BudgetBreakdown(
            total_estimated=known_subtotal,
            known_subtotal=known_subtotal,
            unknown_categories=[],
            omitted_categories=[],
            price_type="estimate",
            categories=categories,
        )


def _price_bounds(quote: object) -> tuple[Decimal | None, Decimal | None]:
    amount = getattr(quote, "amount", None)
    if amount is not None:
        return amount, amount
    return getattr(quote, "amount_min", None), getattr(quote, "amount_max", None)
