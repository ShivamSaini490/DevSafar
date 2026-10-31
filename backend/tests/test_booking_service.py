from datetime import date, datetime

import pytest

from app.core.config import Settings
from app.integrations.booking_provider import BOOKING_NOTICE
from app.schemas.common import BookingLink, PriceQuote
from app.schemas.transport import RouteLeg
from app.schemas.trip import TripRequirements
from app.services.booking_service import BookingService
from app.utils.datetime_utils import INDIA_TIME_ZONE


def _requirements() -> TripRequirements:
    return TripRequirements(
        origin="Hyderabad<script>alert(1)</script>",
        destinations=["Vijayawada"],
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 2),
    )


def _road_leg() -> RouteLeg:
    fetched_at = datetime(2026, 10, 30, tzinfo=INDIA_TIME_ZONE)
    return RouteLeg(
        origin="Hyderabad<script>alert(1)</script>",
        destination="Vijayawada",
        mode="road",
        duration_minutes=220,
        departure_at=datetime(2026, 11, 1, 6, 0, tzinfo=INDIA_TIME_ZONE),
        arrival_at=datetime(2026, 11, 1, 9, 40, tzinfo=INDIA_TIME_ZONE),
        price=PriceQuote(
            amount=None,
            price_type="unknown",
            source="stub",
            fetched_at=fetched_at,
        ),
    )


def test_road_plan_gets_validated_transport_alternatives_and_hotel_search(
    settings: Settings,
) -> None:
    links = BookingService(settings).build(_requirements(), [_road_leg()])

    assert len(links) == 6
    assert {link.mode for link in links} == {"train", "bus", "flight", "hotel"}
    assert sum(link.mode == "train" for link in links) == 2
    assert sum(link.mode == "flight" for link in links) == 2
    assert all(link.link_type == "search_page" for link in links)
    assert all(link.price_known is False for link in links)
    assert all(link.note == BOOKING_NOTICE for link in links)
    assert all(link.origin == _road_leg().origin for link in links)
    assert all(link.destination == "Vijayawada" for link in links)
    assert all(link.date == date(2026, 11, 1) for link in links)
    assert all("<script>" not in str(link.url) for link in links)
    assert all(link.url.query is None for link in links)


class FakeBadProvider:
    def __init__(self, url: str) -> None:
        self.url = url

    def links(
        self,
        requirements: TripRequirements,
        route_legs: list[RouteLeg],
    ) -> list[BookingLink]:
        del requirements, route_legs
        return [
            BookingLink.model_validate(
                {
                    "provider": "bad",
                    "mode": "train",
                    "label": "Unsafe link",
                    "url": self.url,
                    "origin": "Hyderabad",
                    "destination": "Vijayawada",
                    "date": "2026-11-01",
                    "link_type": "search_page",
                    "price_known": False,
                    "note": BOOKING_NOTICE,
                }
            )
        ]


@pytest.mark.parametrize(
    "url",
    ["http://www.irctc.co.in/nget/train-search", "https://evil.example/search"],
)
def test_booking_service_rejects_non_https_or_non_allowlisted_urls(
    settings: Settings,
    url: str,
) -> None:
    service = BookingService(settings, provider=FakeBadProvider(url))

    with pytest.raises(ValueError):
        service.build(_requirements(), [_road_leg()])
