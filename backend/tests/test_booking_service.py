from datetime import date, datetime

import pytest

from app.core.config import Settings
from app.integrations.base import StubHotelProvider
from app.integrations.booking_provider import BOOKING_NOTICE, FLIGHT_NOTICE
from app.schemas.common import BookingLink, PriceQuote
from app.schemas.hotel import HotelOption
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


def _hotel() -> HotelOption:
    fetched_at = datetime(2026, 10, 30, tzinfo=INDIA_TIME_ZONE)
    nightly = PriceQuote(
        amount=1500,
        price_type="estimate",
        source="stub",
        fetched_at=fetched_at,
    )
    return HotelOption(
        destination="Vijayawada",
        name="Estimated stay budget in Vijayawada (no live hotel data)",
        check_in=date(2026, 11, 1),
        check_out=date(2026, 11, 2),
        nightly_price=nightly,
        total_price=nightly,
        availability="unknown",
    )


def test_road_plan_gets_validated_transport_alternatives_and_hotel_search(
    settings: Settings,
) -> None:
    links = BookingService(settings).build(_requirements(), [_road_leg()], [_hotel()])

    assert len(links) == 6
    assert {link.mode for link in links} == {"train", "bus", "flight", "hotel"}
    assert sum(link.mode == "train" for link in links) == 2
    assert sum(link.mode == "flight" for link in links) == 2
    assert all(link.link_type == "search_page" for link in links)
    assert all(link.price_known is False for link in links)
    assert all(link.destination == "Vijayawada" for link in links)
    assert all(link.date == date(2026, 11, 1) for link in links)
    assert all("<script>" not in str(link.url) for link in links)
    assert all(link.url.query is None for link in links)
    transport_links = [link for link in links if link.mode != "hotel"]
    assert all(link.leg_index == 0 and link.stay_index is None for link in transport_links)
    assert all(link.origin == _road_leg().origin for link in transport_links)
    assert all(link.check_in is None and link.check_out is None for link in transport_links)
    flight_links = [link for link in links if link.mode == "flight"]
    assert all(link.note == FLIGHT_NOTICE for link in flight_links)
    hotel_link = next(link for link in links if link.mode == "hotel")
    assert hotel_link.origin is None
    assert hotel_link.leg_index is None
    assert hotel_link.stay_index == 0
    assert hotel_link.check_in == date(2026, 11, 1)
    assert hotel_link.check_out == date(2026, 11, 2)
    assert hotel_link.note == BOOKING_NOTICE


class FakeBadProvider:
    def __init__(self, url: str) -> None:
        self.url = url

    def links(
        self,
        requirements: TripRequirements,
        route_legs: list[RouteLeg],
        hotels: list[HotelOption],
    ) -> list[BookingLink]:
        del requirements, route_legs, hotels
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
                    "leg_index": 0,
                    "link_type": "search_page",
                    "price_known": False,
                    "note": BOOKING_NOTICE,
                }
            )
        ]


class FakeDuplicateProvider:
    def links(
        self,
        requirements: TripRequirements,
        route_legs: list[RouteLeg],
        hotels: list[HotelOption],
    ) -> list[BookingLink]:
        del requirements, route_legs, hotels
        payload = {
            "provider": "IRCTC",
            "mode": "train",
            "label": "Search trains on IRCTC",
            "url": "https://www.irctc.co.in/nget/train-search",
            "origin": "Hyderabad",
            "destination": "Vijayawada",
            "date": "2026-11-01",
            "leg_index": 0,
            "link_type": "search_page",
            "price_known": False,
            "note": BOOKING_NOTICE,
        }
        return [BookingLink.model_validate(payload), BookingLink.model_validate(payload)]


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
        service.build(_requirements(), [_road_leg()], [_hotel()])


def test_booking_service_deduplicates_identical_grouped_links(
    settings: Settings,
) -> None:
    links = BookingService(settings, provider=FakeDuplicateProvider()).build(
        _requirements(),
        [_road_leg()],
        [_hotel()],
    )

    assert len(links) == 1
    assert links[0].leg_index == 0


@pytest.mark.asyncio
async def test_stub_hotel_uses_user_visible_estimate_name() -> None:
    options = await StubHotelProvider(
        datetime(2026, 10, 30, tzinfo=INDIA_TIME_ZONE)
    ).options(_requirements())

    assert options[0].name == (
        "Estimated stay budget in Vijayawada (no live hotel data)"
    )
    assert options[0].nightly_price.source == "stub"
