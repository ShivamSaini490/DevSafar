import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from email.utils import parsedate_to_datetime
from typing import Any, Literal, Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.logging import redact_exception_message
from app.schemas.attraction import AttractionOption
from app.schemas.common import DataSource, PriceQuote, PriceType
from app.schemas.hotel import HotelOption
from app.schemas.transport import RouteLeg, TransportOption
from app.schemas.trip import TripRequirements
from app.services.route_service import ordered_route_stops

ResponseModel = TypeVar("ResponseModel", bound=BaseModel)
ProviderFailureCode = Literal[
    "auth_failed",
    "circuit_open",
    "quota",
    "timeout",
    "server_error",
    "request_error",
    "schema_mismatch",
]


class ProviderFailure(Exception):
    def __init__(self, code: ProviderFailureCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class ProviderCircuitBreaker:
    def __init__(self) -> None:
        self._auth_failed_until: dict[str, datetime] = {}

    def is_open(self, provider: str, *, now: datetime) -> bool:
        until = self._auth_failed_until.get(provider)
        return until is not None and until > now

    def open_auth_failure(
        self,
        provider: str,
        *,
        now: datetime,
        minutes: int,
    ) -> None:
        self._auth_failed_until[provider] = now + timedelta(minutes=minutes)


class SafeProviderHttpClient:
    """Bounded provider HTTP calls with public-safe failures and no secret URLs."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        timeout_seconds: float,
        max_retries: int,
        max_retry_wait_seconds: float,
        auth_circuit_minutes: int,
        circuit_breaker: ProviderCircuitBreaker | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        now_provider: Callable[[], datetime] = lambda: datetime.now(UTC),
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self.client = client
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.max_retry_wait_seconds = max_retry_wait_seconds
        self.auth_circuit_minutes = auth_circuit_minutes
        self.circuit_breaker = circuit_breaker or ProviderCircuitBreaker()
        self.sleep = sleep
        self.now_provider = now_provider
        self.jitter = jitter

    async def get_json(
        self,
        *,
        provider: str,
        url: str,
        params: dict[str, str | int],
        response_model: type[ResponseModel],
        secret_values: tuple[str, ...] = (),
    ) -> ResponseModel:
        if self.circuit_breaker.is_open(provider, now=self.now_provider()):
            raise ProviderFailure("circuit_open", f"{provider} auth circuit is open")
        for attempt in range(self.max_retries + 1):
            try:
                response = await self.client.get(
                    url,
                    params=params,
                    timeout=self.timeout_seconds,
                )
            except httpx.TimeoutException:
                if attempt < self.max_retries:
                    await self._backoff(attempt)
                    continue
                raise ProviderFailure("timeout", f"{provider} request timed out") from None
            except httpx.RequestError as exc:
                safe = redact_exception_message(exc, secret_values=secret_values)
                del safe  # The exception text is intentionally not exposed or re-raised.
                raise ProviderFailure("request_error", f"{provider} request failed") from None

            if response.status_code in {401, 403}:
                self.circuit_breaker.open_auth_failure(
                    provider,
                    now=self.now_provider(),
                    minutes=self.auth_circuit_minutes,
                )
                raise ProviderFailure("auth_failed", f"{provider} authentication failed")
            if response.status_code == 429:
                wait_seconds = _retry_after_seconds(
                    response.headers.get("Retry-After"),
                    now=self.now_provider(),
                )
                if wait_seconds is not None:
                    await self.sleep(min(wait_seconds, self.max_retry_wait_seconds))
                raise ProviderFailure("quota", f"{provider} quota or throughput limit reached")
            if response.status_code >= 500:
                if attempt < self.max_retries:
                    await self._backoff(attempt)
                    continue
                raise ProviderFailure("server_error", f"{provider} server error")
            if response.status_code >= 400:
                raise ProviderFailure("request_error", f"{provider} rejected the request")
            try:
                payload: Any = response.json()
                return response_model.model_validate(payload)
            except (ValueError, ValidationError, TypeError):
                raise ProviderFailure(
                    "schema_mismatch",
                    f"{provider} returned an invalid response",
                ) from None
        raise AssertionError("provider retry loop must return or raise")

    async def _backoff(self, attempt: int) -> None:
        base = min(self.max_retry_wait_seconds, 0.25 * (2**attempt))
        await self.sleep(min(self.max_retry_wait_seconds, base + self.jitter() * 0.1))


def _retry_after_seconds(value: str | None, *, now: datetime) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return max(0.0, (parsed - now).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


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
                    status="unavailable",
                    provider="stub",
                    observed_at=self.fetched_at,
                    price_unit="one route leg",
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
                    status="formula_estimate",
                    provider="stub",
                    observed_at=self.fetched_at,
                    price_unit="one traveller one-way",
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
                name=f"Estimated stay budget in {destination} (no live hotel data)",
                check_in=requirements.start_date,
                check_out=requirements.start_date + timedelta(days=per_destination),
                nightly_price=PriceQuote(
                    amount=nightly,
                    price_type="estimate",
                    source="stub",
                    fetched_at=self.fetched_at,
                    status="formula_estimate",
                    provider="stub",
                    observed_at=self.fetched_at,
                    price_unit="one room per night",
                ),
                total_price=PriceQuote(
                    amount=nightly * per_destination,
                    price_type="estimate",
                    source="stub",
                    fetched_at=self.fetched_at,
                    status="formula_estimate",
                    provider="stub",
                    observed_at=self.fetched_at,
                    price_unit="one room, full stay",
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
                description="Attraction research unavailable for this destination right now.",
                entry_fee=PriceQuote(
                    amount=None,
                    price_type="unknown",
                    source="stub",
                    fetched_at=self.fetched_at,
                    status="unavailable",
                    provider="stub",
                    observed_at=self.fetched_at,
                    price_unit="one adult entry",
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

    def with_places(self, places: PlacesProvider, *, source_name: str) -> "ProviderBundle":
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
    tavily_degraded = bundle.places_source_name == "tavily" and (
        not attractions
        or any(item.source_url is None or item.entry_fee.source == "stub" for item in attractions)
    )
    sources: tuple[tuple[str, PriceType, Literal["ok", "degraded"]], ...] = (
        (
            bundle.maps_source_name,
            maps_price_type,
            "degraded" if bundle.maps_source_name.startswith("stub") else "ok",
        ),
        (
            transport_source[0],
            transport_source[1],
            "degraded" if transport_source[0].startswith("stub") else "ok",
        ),
        ("stub_hotels", "estimate", "degraded"),
        (
            bundle.places_source_name,
            (
                "estimate"
                if bundle.places_source_name == "tavily"
                and any(item.entry_fee.price_type == "estimate" for item in attractions or [])
                else "unknown"
            ),
            (
                "degraded"
                if tavily_degraded or bundle.places_source_name.startswith("stub")
                else "ok"
            ),
        ),
    )
    return [
        DataSource(
            name=name,
            price_type=price_type,
            fetched_at=fetched_at,
            status=status,
        )
        for name, price_type, status in sources
    ]
