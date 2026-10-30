
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol

from app.schemas.attraction import AttractionOption
from app.schemas.common import DataSource, PriceQuote, PriceType
from app.schemas.hotel import HotelOption
from app.schemas.transport import RouteLeg, TransportOption
from app.schemas.trip import TripRequirements


class MapsProvider(Protocol):
    async def route_legs(self, requirements: TripRequirements) -> list[RouteLeg]: ...


class TransportProvider(Protocol):
    async def options(
        self, requirements: TripRequirements
    ) -> list[TransportOption]: ...


class HotelProvider(Protocol):
    async def options(self, requirements: TripRequirements) -> list[HotelOption]: ...


class PlacesProvider(Protocol):
    async def attractions(
        self, requirements: TripRequirements
    ) -> list[AttractionOption]: ...


class StubMapsProvider:
    def __init__(self, fetched_at: datetime) -> None:
        self.fetched_at = fetched_at

    async def route_legs(self, requirements: TripRequirements) -> list[RouteLeg]:
        if requirements.origin is None:
            return []
        stops = [requirements.origin, *requirements.destinations]
        return [
            RouteLeg(
                origin=origin,
                destination=destination,
                mode="unknown",
                duration_minutes=480,
                distance_km=None,
                price=PriceQuote(
                    amount=None,
                    price_type="unknown",
                    source="stub",
                    fetched_at=self.fetched_at,
                ),
            )
            for origin, destination in zip(stops, stops[1:], strict=False)
        ]


class StubTransportProvider:
    def __init__(self, fetched_at: datetime) -> None:
        self.fetched_at = fetched_at

    async def options(self, requirements: TripRequirements) -> list[TransportOption]:
        if requirements.origin is None:
            return []
        stops = [requirements.origin, *requirements.destinations]
        return [
            TransportOption(
                origin=origin,
                destination=destination,
                mode="road",
                provider="stub",
                duration_minutes=480,
                price=PriceQuote(
                    amount=Decimal("2500.00"),
                    price_type="estimate",
                    source="stub",
                    fetched_at=self.fetched_at,
                ),
                availability="unknown",
            )
            for origin, destination in zip(stops, stops[1:], strict=False)
        ]


class StubHotelProvider:
    def __init__(self, fetched_at: datetime) -> None:
        self.fetched_at = fetched_at

    async def options(self, requirements: TripRequirements) -> list[HotelOption]:
        if requirements.start_date is None or requirements.end_date is None:
            return []
        destinations = [
            destination
            for destination in requirements.destinations
            if destination != requirements.origin
        ]
        if not destinations:
            return []
        nights = max(1, (requirements.end_date - requirements.start_date).days)
        per_destination = max(1, nights // len(destinations))
        nightly = Decimal("1500.00")
        return [
            HotelOption(
                destination=destination,
                name=f"Stub stay in {destination}",
                check_in=requirements.start_date,
                check_out=requirements.start_date + timedelta(days=per_destination),
                nightly_price=PriceQuote(
                    amount=nightly,
                    price_type="estimate",
                    source="stub",
                    fetched_at=self.fetched_at,
                ),
                total_price=PriceQuote(
                    amount=nightly * per_destination,
                    price_type="estimate",
                    source="stub",
                    fetched_at=self.fetched_at,
                ),
                availability="unknown",
            )
            for destination in destinations
        ]


class StubPlacesProvider:
    def __init__(self, fetched_at: datetime) -> None:
        self.fetched_at = fetched_at

    async def attractions(
        self, requirements: TripRequirements
    ) -> list[AttractionOption]:
        return [
            AttractionOption(
                destination=destination,
                name=f"Stub attraction in {destination}",
                description="Placeholder only; live places data is not connected.",
                entry_fee=PriceQuote(
                    amount=None,
                    price_type="unknown",
                    source="stub",
                    fetched_at=self.fetched_at,
                ),
                opening_hours=None,
            )
            for destination in requirements.destinations
            if destination != requirements.origin
        ]


@dataclass(frozen=True, slots=True)
class ProviderBundle:
    maps: MapsProvider
    transport: TransportProvider
    hotels: HotelProvider
    places: PlacesProvider

    @classmethod
    def stubs(cls, fetched_at: datetime) -> "ProviderBundle":
        return cls(
            maps=StubMapsProvider(fetched_at),
            transport=StubTransportProvider(fetched_at),
            hotels=StubHotelProvider(fetched_at),
            places=StubPlacesProvider(fetched_at),
        )


def stub_sources(fetched_at: datetime) -> list[DataSource]:
    sources: tuple[tuple[str, PriceType], ...] = (
        ("stub_maps", "unknown"),
        ("stub_transport", "estimate"),
        ("stub_hotels", "estimate"),
        ("stub_places", "unknown"),
    )
    return [
        DataSource(name=name, price_type=price_type, fetched_at=fetched_at)
        for name, price_type in sources
    ]
