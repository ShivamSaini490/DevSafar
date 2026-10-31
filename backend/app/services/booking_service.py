
from app.core.config import Settings
from app.integrations.booking_provider import (
    BookingProvider,
    OfficialSearchPageBookingProvider,
)
from app.schemas.common import BookingLink
from app.schemas.hotel import HotelOption
from app.schemas.transport import RouteLeg
from app.schemas.trip import TripRequirements
from app.utils.url_validator import validate_external_url


class BookingService:
    def __init__(
        self,
        settings: Settings,
        *,
        provider: BookingProvider | None = None,
    ) -> None:
        self.allowed_hosts = settings.booking_host_allowlist
        self.provider = provider or OfficialSearchPageBookingProvider()

    def build(
        self,
        requirements: TripRequirements,
        route_legs: list[RouteLeg],
        hotels: list[HotelOption],
    ) -> list[BookingLink]:
        validated: list[BookingLink] = []
        seen: set[tuple[object, ...]] = set()
        for link in self.provider.links(requirements, route_legs, hotels):
            normalized_url = validate_external_url(
                str(link.url),
                allowed_hosts=self.allowed_hosts,
            )
            payload = link.model_dump()
            payload["url"] = normalized_url
            normalized = BookingLink.model_validate(payload)
            identity = (
                normalized.provider.casefold(),
                normalized.mode,
                str(normalized.url),
                normalized.origin,
                normalized.destination,
                normalized.date,
                normalized.leg_index,
                normalized.stay_index,
                normalized.check_in,
                normalized.check_out,
            )
            if identity in seen:
                continue
            seen.add(identity)
            validated.append(normalized)
        return validated
