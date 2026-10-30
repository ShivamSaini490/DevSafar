
import asyncio
import hashlib
import logging
import time
from collections.abc import Awaitable, Callable
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from redis.asyncio import Redis

from app.core.config import Settings
from app.core.security import utc_now
from app.schemas.common import PriceQuote
from app.schemas.transport import RouteLeg
from app.schemas.trip import TripRequirements
from app.services.route_service import ordered_route_stops
from app.utils.url_validator import validate_external_base_url

logger = logging.getLogger(__name__)

MAX_RETRIES = 2
RETRY_BACKOFF_SECONDS = 0.25
NOMINATIM_MIN_INTERVAL_SECONDS = 1.0


class _ProviderResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")


class GeoPoint(_ProviderResponse):
    lat: Decimal = Field(ge=-90, le=90)
    lon: Decimal = Field(ge=-180, le=180)


class _OsrmLeg(_ProviderResponse):
    distance: Decimal = Field(ge=0)
    duration: Decimal = Field(ge=0)


class _OsrmRoute(_ProviderResponse):
    legs: list[_OsrmLeg]


class _OsrmResponse(_ProviderResponse):
    code: str
    routes: list[_OsrmRoute]


_NOMINATIM_RESULTS = TypeAdapter(list[GeoPoint])


class OsmMapsProvider:
    """Nominatim geocoding plus OSRM road routing with conservative fallbacks."""

    def __init__(
        self,
        settings: Settings,
        redis: Redis,
        *,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self.redis = redis
        self.client = client
        self._sleep = sleep
        self._monotonic = monotonic
        self._nominatim_lock = asyncio.Lock()
        self._last_nominatim_request: float | None = None
        self._geocode_locks: dict[str, asyncio.Lock] = {}
        allowlist = settings.maps_host_allowlist
        self._nominatim_base_url = validate_external_base_url(
            settings.nominatim_base_url,
            allowed_hosts=allowlist,
        )
        self._osrm_base_url = validate_external_base_url(
            settings.osrm_base_url,
            allowed_hosts=allowlist,
        )

    async def route_legs(self, requirements: TripRequirements) -> list[RouteLeg]:
        stops = ordered_route_stops(requirements)
        pairs = list(zip(stops, stops[1:], strict=False))
        if not pairs:
            return []

        points: list[GeoPoint] = []
        for city in stops:
            point = await self.geocode(city)
            if point is None:
                return self._unknown_legs(pairs)
            points.append(point)

        coordinates = ";".join(f"{point.lon},{point.lat}" for point in points)
        payload = await self._get_json(
            f"{self._osrm_base_url}/route/v1/driving/{coordinates}",
            params={"overview": "false", "steps": "false"},
            apply_nominatim_rate_limit=False,
        )
        if payload is None:
            return self._unknown_legs(pairs)
        try:
            response = _OsrmResponse.model_validate(payload)
        except ValidationError:
            logger.warning("OSRM response failed schema validation")
            return self._unknown_legs(pairs)
        if response.code != "Ok" or not response.routes:
            return self._unknown_legs(pairs)
        osrm_legs = response.routes[0].legs
        if len(osrm_legs) != len(pairs):
            logger.warning("OSRM response returned an unexpected leg count")
            return self._unknown_legs(pairs)

        fetched_at = utc_now()
        legs: list[RouteLeg] = []
        for (origin, destination), result in zip(pairs, osrm_legs, strict=True):
            distance_km = (result.distance / Decimal("1000")).quantize(
                Decimal("0.001"), rounding=ROUND_HALF_UP
            )
            duration_minutes = int(
                (result.duration / Decimal("60")).to_integral_value(rounding=ROUND_CEILING)
            )
            fuel_estimate = (distance_km * self.settings.fuel_cost_per_km).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            legs.append(
                RouteLeg(
                    origin=origin,
                    destination=destination,
                    mode="road",
                    duration_minutes=duration_minutes,
                    duration_source="osrm",
                    distance_km=distance_km,
                    price=PriceQuote(
                        amount=fuel_estimate,
                        price_type="estimate",
                        source="fuel_formula",
                        fetched_at=fetched_at,
                    ),
                )
            )
        return legs

    async def geocode(self, city: str) -> GeoPoint | None:
        """Geocode one city; only the city name and country code leave the app."""

        cache_key = self._geocode_cache_key(city)
        cached = await self._read_cached_point(cache_key)
        if cached is not None:
            return cached

        lock = self._geocode_locks.setdefault(cache_key, asyncio.Lock())
        async with lock:
            cached = await self._read_cached_point(cache_key)
            if cached is not None:
                return cached
            payload = await self._get_json(
                f"{self._nominatim_base_url}/search",
                params={
                    "q": city,
                    "format": "jsonv2",
                    "limit": "1",
                    "countrycodes": self.settings.nominatim_country_code.casefold(),
                },
                apply_nominatim_rate_limit=True,
            )
            if payload is None:
                return None
            try:
                results = _NOMINATIM_RESULTS.validate_python(payload)
            except ValidationError:
                logger.warning("Nominatim response failed schema validation")
                return None
            if not results:
                return None
            point = results[0]
            try:
                await self.redis.set(
                    cache_key,
                    point.model_dump_json(),
                    ex=self.settings.geocode_cache_ttl_seconds,
                )
            except Exception as exc:
                logger.warning(
                    "Geocode cache write failed",
                    extra={"error_type": type(exc).__name__},
                )
            return point

    async def _read_cached_point(self, cache_key: str) -> GeoPoint | None:
        try:
            value = await self.redis.get(cache_key)
        except Exception as exc:
            logger.warning(
                "Geocode cache read failed",
                extra={"error_type": type(exc).__name__},
            )
            return None
        if value is None:
            return None
        try:
            return GeoPoint.model_validate_json(value)
        except ValidationError:
            await self.redis.delete(cache_key)
            return None

    async def _get_json(
        self,
        url: str,
        *,
        params: dict[str, str],
        apply_nominatim_rate_limit: bool,
    ) -> Any | None:
        for attempt in range(MAX_RETRIES + 1):
            if apply_nominatim_rate_limit:
                await self._wait_for_nominatim_slot()
            try:
                response = await self._send(url, params=params)
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError) as exc:
                retryable = not isinstance(exc, httpx.HTTPStatusError) or (
                    exc.response.status_code == 429 or exc.response.status_code >= 500
                )
                if attempt >= MAX_RETRIES or not retryable:
                    logger.warning(
                        "Map provider request failed",
                        extra={
                            "error_type": type(exc).__name__,
                            "http_status": getattr(getattr(exc, "response", None), "status_code", None),
                        },
                    )
                    return None
                await self._sleep(RETRY_BACKOFF_SECONDS * (2**attempt))
        return None

    async def _send(self, url: str, *, params: dict[str, str]) -> httpx.Response:
        headers = {"User-Agent": self.settings.nominatim_user_agent}
        if self.client is not None:
            return await self.client.get(
                url,
                params=params,
                headers=headers,
                timeout=self.settings.maps_http_timeout_seconds,
            )
        async with httpx.AsyncClient() as client:
            return await client.get(
                url,
                params=params,
                headers=headers,
                timeout=self.settings.maps_http_timeout_seconds,
            )

    async def _wait_for_nominatim_slot(self) -> None:
        async with self._nominatim_lock:
            now = self._monotonic()
            if self._last_nominatim_request is not None:
                wait_seconds = max(
                    0.0,
                    NOMINATIM_MIN_INTERVAL_SECONDS - (now - self._last_nominatim_request),
                )
                if wait_seconds:
                    await self._sleep(wait_seconds)
            self._last_nominatim_request = self._monotonic()

    def _geocode_cache_key(self, city: str) -> str:
        normalized = f"{self.settings.nominatim_country_code.casefold()}:{city.casefold().strip()}"
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return f"devsafar:maps:geocode:v1:{digest}"

    @staticmethod
    def _unknown_legs(pairs: list[tuple[str, str]]) -> list[RouteLeg]:
        fetched_at = utc_now()
        return [
            RouteLeg(
                origin=origin,
                destination=destination,
                mode="road",
                duration_minutes=None,
                duration_source="osrm_unavailable",
                distance_km=None,
                price=PriceQuote(
                    amount=None,
                    price_type="unknown",
                    source="osrm_unavailable",
                    fetched_at=fetched_at,
                ),
            )
            for origin, destination in pairs
        ]
