
from datetime import date
from typing import Literal, Protocol

from app.schemas.common import BookingLink
from app.schemas.transport import RouteLeg
from app.schemas.trip import TripRequirements

BOOKING_NOTICE: Literal["Opening a provider page is not a confirmed booking."] = (
    "Opening a provider page is not a confirmed booking."
)


class BookingProvider(Protocol):
    def links(
        self,
        requirements: TripRequirements,
        route_legs: list[RouteLeg],
    ) -> list[BookingLink]: ...


class OfficialSearchPageBookingProvider:
    """Build provider search-page redirects without invented query parameters."""

    def links(
        self,
        requirements: TripRequirements,
        route_legs: list[RouteLeg],
    ) -> list[BookingLink]:
        links: list[BookingLink] = []
        hotel_destinations: set[str] = set()
        for leg in route_legs:
            travel_date = (
                leg.departure_at.date()
                if leg.departure_at is not None
                else requirements.start_date
            )
            if travel_date is None:
                continue
            specs: tuple[tuple[str, str, str, str], ...] = (
                (
                    "IRCTC",
                    "train",
                    "Search trains on IRCTC",
                    "https://www.irctc.co.in/nget/train-search",
                ),
                (
                    "MakeMyTrip",
                    "train",
                    "Search trains on MakeMyTrip",
                    "https://www.makemytrip.com/railways/",
                ),
                (
                    "redBus",
                    "bus",
                    "Search buses on redBus",
                    "https://www.redbus.in/",
                ),
                (
                    "MakeMyTrip",
                    "flight",
                    "Search flights on MakeMyTrip",
                    "https://www.makemytrip.com/flights/",
                ),
                (
                    "Google Flights",
                    "flight",
                    "Search flights on Google Flights",
                    "https://www.google.com/travel/flights",
                ),
            )
            links.extend(
                self._link(
                    provider=provider,
                    mode=mode,
                    label=label,
                    url=url,
                    origin=leg.origin,
                    destination=leg.destination,
                    travel_date=travel_date,
                )
                for provider, mode, label, url in specs
            )
            if leg.destination == requirements.origin or leg.destination in hotel_destinations:
                continue
            hotel_destinations.add(leg.destination)
            hotel_date = (
                leg.arrival_at.date() if leg.arrival_at is not None else travel_date
            )
            links.append(
                self._link(
                    provider="Booking.com",
                    mode="hotel",
                    label="Search hotels on Booking.com main search page",
                    url="https://www.booking.com/",
                    origin=leg.origin,
                    destination=leg.destination,
                    travel_date=hotel_date,
                )
            )
        return links

    @staticmethod
    def _link(
        *,
        provider: str,
        mode: str,
        label: str,
        url: str,
        origin: str,
        destination: str,
        travel_date: date,
    ) -> BookingLink:
        return BookingLink.model_validate(
            {
                "provider": provider,
                "mode": mode,
                "label": label,
                "url": url,
                "origin": origin,
                "destination": destination,
                "date": travel_date,
                "link_type": "search_page",
                "price_known": False,
                "note": BOOKING_NOTICE,
            }
        )
