from datetime import date, datetime, timedelta

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
        *,
        use_stub_defaults: bool = True,
        max_driving_hours_per_day: int = 10,
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
                duration = DEFAULT_STUB_DURATION_MINUTES if use_stub_defaults else None
                selected.append(
                    RouteLeg(
                        origin=origin,
                        destination=destination,
                        mode="unknown" if use_stub_defaults else "road",
                        duration_minutes=duration,
                        duration_source="stub_default" if use_stub_defaults else "osrm_unavailable",
                        price=PriceQuote(
                            amount=None,
                            price_type="unknown",
                            source=("stub_route_schedule" if use_stub_defaults else "osrm_unavailable"),
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
        previous_arrival: datetime | None = None
        schedule_known = True
        driven_minutes_by_date: dict[date, int] = {}
        daily_limit_minutes = max_driving_hours_per_day * 60
        scheduled: list[RouteLeg] = []
        for index, leg in enumerate(selected):
            day_offset = 0 if leg_count == 1 else (index * (day_count - 1)) // (leg_count - 1)
            planned_departure = at_india_time(
                requirements.start_date + timedelta(days=day_offset),
                hour=DEFAULT_DEPARTURE_HOUR,
            )
            departure_at: datetime | None = (
                max(planned_departure, previous_arrival)
                if previous_arrival is not None
                else planned_departure
            )
            if not schedule_known:
                departure_at = None
            duration_minutes = leg.duration_minutes
            duration_source = leg.duration_source
            if duration_minutes is None and use_stub_defaults:
                duration_minutes = DEFAULT_STUB_DURATION_MINUTES
                duration_source = "stub_default"
            if duration_minutes is None or departure_at is None:
                arrival_at = None
                overnight_stops = 0
                schedule_known = False
            else:
                arrival_at, overnight_stops = RouteService._add_driving_time(
                    departure_at,
                    duration_minutes,
                    daily_limit_minutes=daily_limit_minutes,
                    driven_minutes_by_date=driven_minutes_by_date,
                )
            scheduled.append(
                leg.model_copy(
                    update={
                        "duration_minutes": duration_minutes,
                        "duration_source": duration_source,
                        "departure_at": departure_at,
                        "arrival_at": arrival_at,
                        "overnight_stops": overnight_stops,
                    }
                )
            )
            if arrival_at is not None:
                previous_arrival = arrival_at
        return scheduled

    @staticmethod
    def _add_driving_time(
        departure_at: datetime,
        duration_minutes: int,
        *,
        daily_limit_minutes: int,
        driven_minutes_by_date: dict[date, int],
    ) -> tuple[datetime, int]:
        current = departure_at
        remaining = duration_minutes
        overnight_stops = 0
        while remaining > 0:
            driving_date = current.date()
            used_today = driven_minutes_by_date.get(driving_date, 0)
            available_today = daily_limit_minutes - used_today
            if available_today <= 0:
                current = at_india_time(current.date() + timedelta(days=1), hour=6)
                overnight_stops += 1
                continue
            driving_now = min(remaining, available_today)
            current += timedelta(minutes=driving_now)
            driven_minutes_by_date[driving_date] = used_today + driving_now
            remaining -= driving_now
            if remaining > 0:
                current = at_india_time(current.date() + timedelta(days=1), hour=6)
                overnight_stops += 1
        return current, overnight_stops

    @staticmethod
    def schedule_warnings(route_legs: list[RouteLeg], *, daily_hours: int) -> list[str]:
        return [
            (
                f"Road leg {leg.origin} to {leg.destination} needs "
                f"{leg.overnight_stops} overnight rest stop(s) under the "
                f"{daily_hours}-hour driving-day rule."
            )
            for leg in route_legs
            if leg.overnight_stops > 0
        ]
