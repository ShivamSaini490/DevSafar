
from datetime import date
from typing import Literal, Protocol

from app.schemas.common import BookingLink
from app.schemas.hotel import HotelOption
from app.schemas.transport import RouteLeg
from app.schemas.trip import TripRequirements

BOOKING_NOTICE: Literal["Opening a provider page is not a confirmed booking."] = (
    "Opening a provider page is not a confirmed booking."
)
FLIGHT_NOTICE = (
    f"{BOOKING_NOTICE} "
    "Flights may require the nearest airport; verify availability for this city."
)


class BookingProvider(Protocol):
    def links(
        self,
        requirements: TripRequirements,
        route_legs: list[RouteLeg],
        hotels: list[HotelOption],
    ) -> list[BookingLink]: ...


class OfficialSearchPageBookingProvider:
    """Build provider search-page redirects without invented query parameters."""

    def links(
        self,
        requirements: TripRequirements,
        route_legs: list[RouteLeg],
        hotels: list[HotelOption],
    ) -> list[BookingLink]:
        links: list[BookingLink] = []
        for leg_index, leg in enumerate(route_legs):
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
                    leg_index=leg_index,
                    note=(FLIGHT_NOTICE if mode == "flight" else BOOKING_NOTICE),
                )
                for provider, mode, label, url in specs
            )
        for stay_index, hotel in enumerate(hotels):
            if hotel.destination.casefold() == "en route":
                continue
            links.append(
                self._link(
                    provider="Booking.com",
                    mode="hotel",
                    label="Search hotels on Booking.com main search page",
                    url="https://www.booking.com/",
                    origin=None,
                    destination=hotel.destination,
                    travel_date=hotel.check_in,
                    stay_index=stay_index,
                    check_in=hotel.check_in,
                    check_out=hotel.check_out,
                    note=BOOKING_NOTICE,
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
        origin: str | None,
        destination: str,
        travel_date: date,
        leg_index: int | None = None,
        stay_index: int | None = None,
        check_in: date | None = None,
        check_out: date | None = None,
        note: str = BOOKING_NOTICE,
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
                "leg_index": leg_index,
                "stay_index": stay_index,
                "check_in": check_in,
                "check_out": check_out,
                "link_type": "search_page",
                "price_known": False,
                "note": note,
            }
        )
