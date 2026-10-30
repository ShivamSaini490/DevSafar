
from app.core.security import utc_now
from app.schemas.attraction import AttractionOption
from app.schemas.budget import BudgetBreakdown, BudgetCategory
from app.schemas.hotel import HotelOption
from app.schemas.transport import TransportOption
from app.utils.currency_utils import all_amounts_known, sum_known_amounts


class BudgetService:
    @staticmethod
    def build(
        *,
        transport_options: list[TransportOption],
        hotels: list[HotelOption],
        attractions: list[AttractionOption],
    ) -> BudgetBreakdown:
        priced_transport = [item.price.amount for item in transport_options]
        priced_hotels = [item.total_price.amount for item in hotels]
        attraction_prices = [item.entry_fee.amount for item in attractions]
        fetched_at = next(
            iter(
                [item.price.fetched_at for item in transport_options]
                + [item.total_price.fetched_at for item in hotels]
                + [item.entry_fee.fetched_at for item in attractions]
            ),
            utc_now(),
        )
        categories = [
            BudgetCategory(
                name="Transport",
                amount=sum_known_amounts(priced_transport),
                price_type="estimate",
                source="stub",
                fetched_at=fetched_at,
            ),
            BudgetCategory(
                name="Hotels",
                amount=sum_known_amounts(priced_hotels),
                price_type="estimate",
                source="stub",
                fetched_at=fetched_at,
            ),
        ]
        if attractions:
            if not all_amounts_known(attraction_prices):
                categories.append(
                    BudgetCategory(
                        name="Attractions",
                        amount=None,
                        price_type="unknown",
                        source="stub",
                        fetched_at=fetched_at,
                    )
                )
            else:
                categories.append(
                    BudgetCategory(
                        name="Attractions",
                        amount=sum_known_amounts(attraction_prices),
                        price_type="estimate",
                        source="stub",
                        fetched_at=fetched_at,
                    )
                )
        if any(category.amount is None for category in categories):
            return BudgetBreakdown(
                total_estimated=None,
                price_type="unknown",
                categories=categories,
            )
        total = sum_known_amounts(category.amount for category in categories)
        return BudgetBreakdown(
            total_estimated=total,
            price_type="estimate",
            categories=categories,
        )
