from collections import defaultdict
from datetime import date, datetime, time, timedelta

from app.schemas.itinerary import ItineraryActivity, ItineraryDay
from app.schemas.transport import RouteLeg
from app.schemas.trip import TripRequirements
from app.utils.datetime_utils import INDIA_TIME_ZONE, as_india_time, at_india_time, india_now


class ItineraryService:
    @staticmethod
    def build(
        requirements: TripRequirements,
        route_legs: list[RouteLeg],
        *,
        min_stay_hours_per_destination: int = 6,
        now: datetime | None = None,
    ) -> list[ItineraryDay]:
        if requirements.start_date is None or requirements.end_date is None:
            return []

        current_time = as_india_time(now or india_now())
        activities_by_date: dict[date, list[ItineraryActivity]] = defaultdict(list)
        end_location_events: dict[date, list[tuple[datetime, str]]] = defaultdict(list)
        for index, leg in enumerate(route_legs):
            for segment_index, segment in enumerate(leg.driving_segments):
                arrives_at_destination = (
                    leg.arrival_at is not None and segment.ends_at == leg.arrival_at
                )
                activities_by_date[segment.starts_at.date()].append(
                    ItineraryActivity(
                        title=(
                            f"Drive from {leg.origin} toward {leg.destination}"
                            if segment_index == 0
                            else f"Continue driving toward {leg.destination}"
                        ),
                        location=f"{leg.origin} to {leg.destination}",
                        starts_at=segment.starts_at,
                        ends_at=segment.ends_at,
                        notes=(
                            f"Road duration source: {leg.duration_source or 'unverified'}; "
                            "scheduled within the configured driving-day limit."
                        ),
                    )
                )
                end_location_events[segment.ends_at.date()].append(
                    (
                        segment.ends_at,
                        leg.destination if arrives_at_destination else "en route",
                    )
                )

            if leg.arrival_at is None:
                continue
            arrival_at = leg.arrival_at
            next_departure = (
                route_legs[index + 1].departure_at
                if index + 1 < len(route_legs) and route_legs[index + 1].origin == leg.destination
                else None
            )
            activities_by_date[arrival_at.date()].append(
                ItineraryActivity(
                    title=f"Arrive in {leg.destination}",
                    location=leg.destination,
                    starts_at=arrival_at,
                    ends_at=arrival_at,
                    notes=(
                        f"Arrival after {leg.duration_minutes} minutes of "
                        f"{leg.mode} travel; duration source: "
                        f"{leg.duration_source or 'unverified'}."
                        + (
                            f" Includes {leg.overnight_stops} overnight driving rest stop(s)."
                            if leg.overnight_stops
                            else ""
                        )
                    ),
                )
            )

            if leg.destination == requirements.origin:
                continue
            minimum_stay_end = arrival_at + timedelta(
                hours=min_stay_hours_per_destination
            )
            stay_end = max(minimum_stay_end, next_departure or minimum_stay_end)
            activities_by_date[arrival_at.date()].append(
                ItineraryActivity(
                    title=f"Stay in {leg.destination}",
                    location=leg.destination,
                    starts_at=arrival_at,
                    ends_at=stay_end,
                    notes=(
                        f"Minimum destination stay: {min_stay_hours_per_destination} hours."
                    ),
                )
            )

        last_arrival_date = max(
            (leg.arrival_at.date() for leg in route_legs if leg.arrival_at is not None),
            default=requirements.end_date,
        )
        final_date = max(requirements.end_date, last_arrival_date)
        latest_activity_date = max(
            (
                activity.ends_at.date()
                for activities in activities_by_date.values()
                for activity in activities
                if activity.ends_at is not None
            ),
            default=final_date,
        )
        final_date = max(final_date, latest_activity_date)
        current_destination = requirements.origin or "Unknown"
        days: list[ItineraryDay] = []
        day_date = requirements.start_date
        day_number = 1
        while day_date <= final_date:
            events_today = sorted(
                end_location_events.get(day_date, []),
                key=lambda event: event[0],
            )
            if events_today:
                current_destination = events_today[-1][1]
            activities: list[ItineraryActivity] = []
            for activity in activities_by_date.get(day_date, []):
                if activity.ends_at is not None and activity.ends_at <= current_time:
                    continue
                starts_at = activity.starts_at
                if starts_at is not None and starts_at < current_time:
                    starts_at = current_time
                if (
                    starts_at is not None
                    and activity.ends_at is not None
                    and activity.ends_at < starts_at
                ):
                    continue
                activities.append(activity.model_copy(update={"starts_at": starts_at}))
            activities = sorted(
                activities,
                key=lambda activity: (
                    activity.starts_at
                    or datetime.combine(
                        day_date,
                        time.min,
                        tzinfo=INDIA_TIME_ZONE,
                    )
                ),
            )
            if day_date < current_time.date():
                day_date += timedelta(days=1)
                continue
            if not activities:
                flexible_start = at_india_time(day_date, hour=10)
                if day_date == current_time.date():
                    flexible_start = max(flexible_start, current_time)
                flexible_end = max(
                    at_india_time(day_date, hour=18),
                    flexible_start + timedelta(hours=1),
                )
                activities = [
                    ItineraryActivity(
                        title=f"Flexible/rest day in {current_destination}",
                        location=current_destination,
                        starts_at=flexible_start,
                        ends_at=flexible_end,
                        notes="No provider-backed activity is scheduled for this day.",
                    )
                ]
            days.append(
                ItineraryDay(
                    day=day_number,
                    date=day_date,
                    destination=current_destination,
                    activities=activities,
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
