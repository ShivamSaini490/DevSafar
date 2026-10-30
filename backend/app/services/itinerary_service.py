
from datetime import datetime, timedelta

from app.schemas.itinerary import ItineraryActivity, ItineraryDay
from app.schemas.trip import TripRequirements
from app.utils.datetime_utils import at_india_time


class ItineraryService:
    @staticmethod
    def build(requirements: TripRequirements) -> list[ItineraryDay]:
        if requirements.start_date is None or requirements.end_date is None:
            return []
        destinations = requirements.destinations or [requirements.origin or "Unknown"]
        day_count = (requirements.end_date - requirements.start_date).days + 1
        return [
            ItineraryDay(
                day=index + 1,
                date=requirements.start_date + timedelta(days=index),
                destination=destinations[min(index, len(destinations) - 1)],
                activities=[
                    ItineraryActivity(
                        title="Stub itinerary activity",
                        location=destinations[min(index, len(destinations) - 1)],
                        starts_at=at_india_time(
                            requirements.start_date + timedelta(days=index), hour=10
                        ),
                        ends_at=at_india_time(
                            requirements.start_date + timedelta(days=index), hour=12
                        ),
                        notes="Placeholder schedule; providers are not connected.",
                    )
                ],
            )
            for index in range(day_count)
        ]

    @staticmethod
    def planned_return_at(requirements: TripRequirements) -> datetime | None:
        if requirements.end_date is None:
            return None
        return at_india_time(requirements.end_date, hour=20)
