from datetime import date, datetime, timedelta

from app.core.security import utc_now
from app.schemas.common import PriceQuote
from app.schemas.transport import DrivingSegment, RouteLeg
from app.schemas.trip import TripRequirements
from app.utils.datetime_utils import (
    as_india_time,
    at_india_time,
    india_now,
    next_sensible_slot,
)

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
        min_stay_hours_per_destination: int = 6,
        now: datetime | None = None,
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

        previous_arrival: datetime | None = None
        schedule_known = True
        driven_minutes_by_date: dict[date, int] = {}
        daily_limit_minutes = max_driving_hours_per_day * 60
        current_time = as_india_time(now or india_now())
        scheduled: list[RouteLeg] = []
        for index, leg in enumerate(selected):
            if index == 0:
                planned_departure = at_india_time(
                    requirements.start_date,
                    hour=DEFAULT_DEPARTURE_HOUR,
                )
            elif previous_arrival is not None:
                stay_hours = (
                    min_stay_hours_per_destination
                    if requirements.origin is None
                    or leg.origin.casefold() != requirements.origin.casefold()
                    else 0
                )
                planned_departure = previous_arrival + timedelta(hours=stay_hours)
            else:
                planned_departure = at_india_time(
                    requirements.start_date,
                    hour=DEFAULT_DEPARTURE_HOUR,
                )
            if index == 0 and requirements.start_date == current_time.date():
                planned_departure = max(
                    planned_departure,
                    next_sensible_slot(current_time),
                )
            departure_at: datetime | None = (
                max(planned_departure, previous_arrival)
                if previous_arrival is not None
                else planned_departure
            )
            if not schedule_known:
                departure_at = None
            elif departure_at is not None:
                departure_at = RouteService._normalize_driving_start(
                    departure_at,
                    daily_limit_minutes=daily_limit_minutes,
                    driven_minutes_by_date=driven_minutes_by_date,
                )
            duration_minutes = leg.duration_minutes
            duration_source = leg.duration_source
            if duration_minutes is None and use_stub_defaults:
                duration_minutes = DEFAULT_STUB_DURATION_MINUTES
                duration_source = "stub_default"
            if duration_minutes is None or departure_at is None:
                arrival_at = None
                overnight_stops = 0
                driving_segments: list[DrivingSegment] = []
                schedule_known = False
            else:
                arrival_at, overnight_stops, driving_segments = RouteService._add_driving_time(
                    departure_at,
                    duration_minutes,
                    daily_limit_minutes=daily_limit_minutes,
                    driven_minutes_by_date=driven_minutes_by_date,
                )
                if driving_segments:
                    departure_at = driving_segments[0].starts_at
            scheduled.append(
                leg.model_copy(
                    update={
                        "duration_minutes": duration_minutes,
                        "duration_source": duration_source,
                        "departure_at": departure_at,
                        "arrival_at": arrival_at,
                        "overnight_stops": overnight_stops,
                        "driving_segments": driving_segments,
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
    ) -> tuple[datetime, int, list[DrivingSegment]]:
        current = departure_at
        remaining = duration_minutes
        overnight_stops = 0
        segments: list[DrivingSegment] = []
        while remaining > 0:
            driving_date = current.date()
            used_today = driven_minutes_by_date.get(driving_date, 0)
            driving_day_end = at_india_time(driving_date, hour=6) + timedelta(
                minutes=daily_limit_minutes
            )
            clock_minutes_left = max(
                0,
                int((driving_day_end - current).total_seconds() // 60),
            )
            available_today = min(
                daily_limit_minutes - used_today,
                clock_minutes_left,
            )
            if available_today <= 0:
                current = at_india_time(current.date() + timedelta(days=1), hour=6)
                overnight_stops += 1
                continue
            driving_now = min(remaining, available_today)
            segment_start = current
            current = segment_start + timedelta(minutes=driving_now)
            segments.append(DrivingSegment(starts_at=segment_start, ends_at=current))
            driven_minutes_by_date[driving_date] = used_today + driving_now
            remaining -= driving_now
            if remaining > 0:
                current = at_india_time(current.date() + timedelta(days=1), hour=6)
                overnight_stops += 1
        return current, overnight_stops, segments

    @staticmethod
    def _normalize_driving_start(
        candidate: datetime,
        *,
        daily_limit_minutes: int,
        driven_minutes_by_date: dict[date, int],
    ) -> datetime:
        current = candidate
        while True:
            day_start = at_india_time(current.date(), hour=6)
            day_end = day_start + timedelta(minutes=daily_limit_minutes)
            if current < day_start:
                current = day_start
            used_today = driven_minutes_by_date.get(current.date(), 0)
            if current < day_end and used_today < daily_limit_minutes:
                return current
            current = at_india_time(current.date() + timedelta(days=1), hour=6)

    @staticmethod
    def schedule_warnings(
        route_legs: list[RouteLeg],
        *,
        daily_hours: int,
        start_date: date | None = None,
        baseline_return_at: datetime | None = None,
    ) -> list[str]:
        warnings = [
            (
                f"Road leg {leg.origin} to {leg.destination} needs "
                f"{leg.overnight_stops} overnight rest stop(s) under the "
                f"{daily_hours}-hour driving-day rule."
            )
            for leg in route_legs
            if leg.overnight_stops > 0
        ]
        if route_legs and route_legs[0].departure_at is not None and start_date is not None:
            first_leg = route_legs[0]
            first_departure = first_leg.departure_at
            if first_departure is None:
                return warnings
            default_departure = at_india_time(start_date, hour=6)
            if first_departure > default_departure:
                actual_return_at = next(
                    (
                        leg.arrival_at
                        for leg in reversed(route_legs)
                        if leg.arrival_at is not None
                    ),
                    None,
                )
                added_hours = (
                    max(
                        0.0,
                        (actual_return_at - baseline_return_at).total_seconds() / 3600,
                    )
                    if actual_return_at is not None and baseline_return_at is not None
                    else (first_departure - default_departure).total_seconds() / 3600
                )
                warnings.insert(
                    0,
                    (
                        f"Schedule start shifted from {default_departure.isoformat()} to "
                        f"{first_departure.isoformat()}; this adds {added_hours:.1f} hours "
                        "to the return arrival."
                    ),
                )
        return warnings
