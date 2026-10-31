from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol

from app.schemas.attraction import AttractionOption
from app.schemas.common import DataSource, PriceQuote, PriceType
from app.schemas.hotel import HotelOption
from app.schemas.transport import RouteLeg, TransportOption
from app.schemas.trip import TripRequirements
from app.services.route_service import ordered_route_stops


class MapsProvider(Protocol):
    async def route_legs(self, requirements: TripRequirements) -> list[RouteLeg]: ...


class TransportProvider(Protocol):
    async def options(self, requirements: TripRequirements) -> list[TransportOption]: ...


class HotelProvider(Protocol):
    async def options(self, requirements: TripRequirements) -> list[HotelOption]: ...


class PlacesProvider(Protocol):
    async def attractions(self, requirements: TripRequirements) -> list[AttractionOption]: ...


class StubMapsProvider:
    def __init__(self, fetched_at: datetime) -> None:
        self.fetched_at = fetched_at

    async def route_legs(self, requirements: TripRequirements) -> list[RouteLeg]:
        if requirements.origin is None:
            return []
        stops = ordered_route_stops(requirements)
        return [
            RouteLeg(
                origin=origin,
                destination=destination,
                mode="unknown",
                duration_minutes=480,
                duration_source="stub",
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
        stops = ordered_route_stops(requirements)
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


class NoTransportProvider:
    async def options(self, requirements: TripRequirements) -> list[TransportOption]:
        del requirements
        return []


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

    async def attractions(self, requirements: TripRequirements) -> list[AttractionOption]:
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
                source_url=None,
                source_domain=None,
                fetched_at=self.fetched_at,
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
    maps_source_name: str
    places_source_name: str

    @classmethod
    def stubs(cls, fetched_at: datetime) -> "ProviderBundle":
        return cls(
            maps=StubMapsProvider(fetched_at),
            transport=StubTransportProvider(fetched_at),
            hotels=StubHotelProvider(fetched_at),
            places=StubPlacesProvider(fetched_at),
            maps_source_name="stub_maps",
            places_source_name="stub_places",
        )

    def with_maps(self, maps: MapsProvider, *, source_name: str) -> "ProviderBundle":
        return ProviderBundle(
            maps=maps,
            transport=(NoTransportProvider() if source_name == "osrm" else self.transport),
            hotels=self.hotels,
            places=self.places,
            maps_source_name=source_name,
            places_source_name=self.places_source_name,
        )

    def with_places(
        self, places: PlacesProvider, *, source_name: str
    ) -> "ProviderBundle":
        return ProviderBundle(
            maps=self.maps,
            transport=self.transport,
            hotels=self.hotels,
            places=places,
            maps_source_name=self.maps_source_name,
            places_source_name=source_name,
        )


def provider_sources(
    bundle: ProviderBundle,
    fetched_at: datetime,
    *,
    attractions: list[AttractionOption] | None = None,
) -> list[DataSource]:
    maps_price_type: PriceType = "estimate" if bundle.maps_source_name == "osrm" else "unknown"
    transport_source: tuple[str, PriceType] = (
        ("osrm+fuel_formula", "estimate")
        if bundle.maps_source_name == "osrm"
        else ("stub_transport", "estimate")
    )
    sources: tuple[tuple[str, PriceType], ...] = (
        (bundle.maps_source_name, maps_price_type),
        transport_source,
        ("stub_hotels", "estimate"),
        (
            bundle.places_source_name,
            (
                "estimate"
                if bundle.places_source_name == "tavily"
                and any(
                    item.entry_fee.price_type == "estimate"
                    for item in attractions or []
                )
                else "unknown"
            ),
        ),
    )
    return [
        DataSource(name=name, price_type=price_type, fetched_at=fetched_at)
        for name, price_type in sources
    ]
