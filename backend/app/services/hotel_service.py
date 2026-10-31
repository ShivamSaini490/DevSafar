from datetime import timedelta

from app.schemas.hotel import HotelOption
from app.schemas.transport import RouteLeg
from app.schemas.trip import TripRequirements


class HotelService:
    @staticmethod
    def align_with_route(
        requirements: TripRequirements,
        route_legs: list[RouteLeg],
        hotel_options: list[HotelOption],
        *,
        min_stay_hours_per_destination: int = 6,
    ) -> list[HotelOption]:
        if requirements.origin is None:
            return []
        aligned: list[HotelOption] = []
        rest_template = hotel_options[0] if hotel_options else None
        if rest_template is not None:
            for leg in route_legs:
                if leg.overnight_stops == 0:
                    continue
                for current_segment, next_segment in zip(
                    leg.driving_segments,
                    leg.driving_segments[1:],
                    strict=False,
                ):
                    check_in = current_segment.ends_at.date()
                    check_out = next_segment.starts_at.date()
                    if check_out <= check_in:
                        continue
                    nightly = rest_template.nightly_price.model_copy(
                        update={"source": "stub_overnight_rest_estimate"}
                    )
                    night = check_in
                    while night < check_out:
                        next_day = night + timedelta(days=1)
                        aligned.append(
                            HotelOption(
                                destination="en route",
                                name=(
                                    "Overnight rest stop between "
                                    f"{leg.origin} and {leg.destination}"
                                ),
                                check_in=night,
                                check_out=next_day,
                                nightly_price=nightly,
                                total_price=nightly.model_copy(deep=True),
                                availability="unknown",
                            )
                        )
                        night = next_day
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
            stay_end = (
                departure_leg.departure_at
                if departure_leg is not None and departure_leg.departure_at is not None
                else arrival_leg.arrival_at
                + timedelta(hours=min_stay_hours_per_destination)
            )
            check_in = arrival_leg.arrival_at.date()
            check_out = stay_end.date()
            if check_out <= check_in:
                continue
            option = next(
                (
                    candidate
                    for candidate in hotel_options
                    if candidate.destination.casefold() == arrival_leg.destination.casefold()
                ),
                None,
            )
            if option is None:
                continue
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
        return sorted(
            aligned,
            key=lambda option: (option.check_in, option.check_out, option.name),
        )
