
from app.core.config import Settings
from app.integrations.booking_provider import (
    BookingProvider,
    OfficialSearchPageBookingProvider,
)
from app.schemas.common import BookingLink
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
    ) -> list[BookingLink]:
        validated: list[BookingLink] = []
        for link in self.provider.links(requirements, route_legs):
            normalized_url = validate_external_url(
                str(link.url),
                allowed_hosts=self.allowed_hosts,
            )
            payload = link.model_dump()
            payload["url"] = normalized_url
            validated.append(BookingLink.model_validate(payload))
        return validated
