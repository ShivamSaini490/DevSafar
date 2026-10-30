from app.schemas.hotel import HotelOption
from app.schemas.transport import RouteLeg
from app.schemas.trip import TripRequirements


class HotelService:
    @staticmethod
    def align_with_route(
        requirements: TripRequirements,
        route_legs: list[RouteLeg],
        hotel_options: list[HotelOption],
    ) -> list[HotelOption]:
        if requirements.origin is None:
            return []
        aligned: list[HotelOption] = []
        used_option_ids: set[int] = set()
        for index, arrival_leg in enumerate(route_legs):
            if arrival_leg.destination == requirements.origin or arrival_leg.arrival_at is None:
                continue
            departure_leg = next(
                (
                    leg
                    for leg in route_legs[index + 1 :]
                    if leg.origin == arrival_leg.destination and leg.departure_at is not None
                ),
                None,
            )
            if departure_leg is None or departure_leg.departure_at is None:
                continue
            check_in = arrival_leg.arrival_at.date()
            check_out = departure_leg.departure_at.date()
            if check_out <= check_in:
                continue
            option = next(
                (
                    candidate
                    for candidate in hotel_options
                    if id(candidate) not in used_option_ids
                    and candidate.destination.casefold() == arrival_leg.destination.casefold()
                ),
                None,
            )
            if option is None:
                continue
            used_option_ids.add(id(option))
            nights = (check_out - check_in).days
            nightly_amount = option.nightly_price.amount
            total_price = option.total_price.model_copy(
                update={
                    "amount": (nightly_amount * nights if nightly_amount is not None else None),
                    "price_type": (
                        option.nightly_price.price_type if nightly_amount is not None else "unknown"
                    ),
                    "source": option.nightly_price.source,
                    "fetched_at": option.nightly_price.fetched_at,
                }
            )
            aligned.append(
                option.model_copy(
                    update={
                        "check_in": check_in,
                        "check_out": check_out,
                        "total_price": total_price,
                    }
                )
            )
        return aligned
