from datetime import timedelta

from app.core.security import utc_now
from app.schemas.common import PriceQuote
from app.schemas.transport import RouteLeg
from app.schemas.trip import TripRequirements
from app.utils.datetime_utils import at_india_time

DEFAULT_STUB_DURATION_MINUTES = 480
DEFAULT_DEPARTURE_HOUR = 6


def ordered_route_stops(requirements: TripRequirements) -> list[str]:
    if requirements.origin is None:
        return []
    stops = [requirements.origin, *requirements.destinations]
    return_requested = requirements.return_deadline is not None or bool(
        requirements.destinations and requirements.destinations[-1] == requirements.origin
    )
    if return_requested and stops[-1] != requirements.origin:
        stops.append(requirements.origin)
    return [stop for index, stop in enumerate(stops) if index == 0 or stop != stops[index - 1]]


class RouteService:
    @staticmethod
    def build_route(
        requirements: TripRequirements,
        route_options: list[RouteLeg],
    ) -> list[RouteLeg]:
        if requirements.start_date is None:
            return []
        stops = ordered_route_stops(requirements)
        expected_pairs = list(zip(stops, stops[1:], strict=False))
        if not expected_pairs:
            return []

        unused_options = list(route_options)
        selected: list[RouteLeg] = []
        for origin, destination in expected_pairs:
            match_index = next(
                (
                    index
                    for index, option in enumerate(unused_options)
                    if option.origin == origin and option.destination == destination
                ),
                None,
            )
            if match_index is None:
                selected.append(
                    RouteLeg(
                        origin=origin,
                        destination=destination,
                        mode="unknown",
                        duration_minutes=DEFAULT_STUB_DURATION_MINUTES,
                        duration_source="stub_default",
                        price=PriceQuote(
                            amount=None,
                            price_type="unknown",
                            source="stub_route_schedule",
                            fetched_at=utc_now(),
                        ),
                    )
                )
            else:
                selected.append(unused_options.pop(match_index))

        day_count = max(
            1,
            (
                (requirements.end_date - requirements.start_date).days + 1
                if requirements.end_date is not None
                else 1
            ),
        )
        leg_count = len(selected)
        previous_arrival = None
        scheduled: list[RouteLeg] = []
        for index, leg in enumerate(selected):
            day_offset = 0 if leg_count == 1 else (index * (day_count - 1)) // (leg_count - 1)
            planned_departure = at_india_time(
                requirements.start_date + timedelta(days=day_offset),
                hour=DEFAULT_DEPARTURE_HOUR,
            )
            departure_at = (
                max(planned_departure, previous_arrival)
                if previous_arrival is not None
                else planned_departure
            )
            duration_minutes = leg.duration_minutes or DEFAULT_STUB_DURATION_MINUTES
            duration_source = leg.duration_source
            if leg.duration_minutes is None:
                duration_source = "stub_default"
            arrival_at = departure_at + timedelta(minutes=duration_minutes)
            scheduled.append(
                leg.model_copy(
                    update={
                        "duration_minutes": duration_minutes,
                        "duration_source": duration_source,
                        "departure_at": departure_at,
                        "arrival_at": arrival_at,
                    }
                )
            )
            previous_arrival = arrival_at
        return scheduled
