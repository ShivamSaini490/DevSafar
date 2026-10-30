from collections import defaultdict
from datetime import date, datetime, time, timedelta

from app.schemas.itinerary import ItineraryActivity, ItineraryDay
from app.schemas.transport import RouteLeg
from app.schemas.trip import TripRequirements
from app.utils.datetime_utils import INDIA_TIME_ZONE, at_india_time


class ItineraryService:
    @staticmethod
    def build(
        requirements: TripRequirements,
        route_legs: list[RouteLeg],
    ) -> list[ItineraryDay]:
        if requirements.start_date is None or requirements.end_date is None:
            return []

        activities_by_date: dict[date, list[ItineraryActivity]] = defaultdict(list)
        destination_by_date: dict[date, str] = {}
        for index, leg in enumerate(route_legs):
            if leg.arrival_at is None:
                continue
            arrival_at = leg.arrival_at
            next_departure = (
                route_legs[index + 1].departure_at
                if index + 1 < len(route_legs) and route_legs[index + 1].origin == leg.destination
                else None
            )
            arrival_end = arrival_at + timedelta(minutes=30)
            if next_departure is not None:
                arrival_end = min(arrival_end, next_departure)
            activities_by_date[arrival_at.date()].append(
                ItineraryActivity(
                    title=f"Arrive in {leg.destination}",
                    location=leg.destination,
                    starts_at=arrival_at,
                    ends_at=max(arrival_at, arrival_end),
                    notes=(
                        f"Arrival after {leg.duration_minutes} minutes of "
                        f"{leg.mode} travel; duration source: "
                        f"{leg.duration_source or 'unverified'}."
                    ),
                )
            )
            destination_by_date[arrival_at.date()] = leg.destination

            if leg.destination == requirements.origin:
                continue
            activity_start = max(
                arrival_at + timedelta(hours=1),
                at_india_time(arrival_at.date(), hour=10),
            )
            activity_end = activity_start + timedelta(hours=2)
            if next_departure is not None:
                activity_end = min(activity_end, next_departure)
            if activity_end > activity_start:
                activities_by_date[activity_start.date()].append(
                    ItineraryActivity(
                        title="Stub itinerary activity",
                        location=leg.destination,
                        starts_at=activity_start,
                        ends_at=activity_end,
                        notes="Placeholder schedule; providers are not connected.",
                    )
                )
                destination_by_date[activity_start.date()] = leg.destination

        last_arrival_date = max(
            (leg.arrival_at.date() for leg in route_legs if leg.arrival_at is not None),
            default=requirements.end_date,
        )
        final_date = max(requirements.end_date, last_arrival_date)
        current_destination = requirements.origin or "Unknown"
        days: list[ItineraryDay] = []
        day_date = requirements.start_date
        day_number = 1
        while day_date <= final_date:
            arrivals_today = [
                leg
                for leg in route_legs
                if leg.arrival_at is not None and leg.arrival_at.date() == day_date
            ]
            if arrivals_today:
                current_destination = arrivals_today[-1].destination
            current_destination = destination_by_date.get(day_date, current_destination)
            days.append(
                ItineraryDay(
                    day=day_number,
                    date=day_date,
                    destination=current_destination,
                    activities=sorted(
                        activities_by_date.get(day_date, []),
                        key=lambda activity: (
                            activity.starts_at
                            or datetime.combine(
                                day_date,
                                time.min,
                                tzinfo=INDIA_TIME_ZONE,
                            )
                        ),
                    ),
                )
            )
            day_date += timedelta(days=1)
            day_number += 1
        return days

    @staticmethod
    def planned_return_at(
        requirements: TripRequirements,
        route_legs: list[RouteLeg],
    ) -> datetime | None:
        if requirements.origin is None:
            return None
        return next(
            (
                leg.arrival_at
                for leg in reversed(route_legs)
                if leg.destination == requirements.origin and leg.arrival_at is not None
            ),
            None,
        )
