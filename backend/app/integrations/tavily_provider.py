import asyncio
import hashlib
import logging
import re
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import datetime
from decimal import Decimal, InvalidOperation
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, HttpUrl, TypeAdapter, ValidationError
from redis.asyncio import Redis

from app.core.config import Settings
from app.schemas.attraction import AttractionOption
from app.schemas.common import PriceQuote
from app.schemas.trip import TripRequirements
from app.utils.url_validator import validate_external_base_url

logger = logging.getLogger(__name__)

MAX_RETRIES = 1
RETRY_BACKOFF_SECONDS = 0.25
MAX_RESULTS = 5

_FEE_PATTERN = re.compile(
    r"(?:entry|entrance|admission|ticket)\s*(?:fee|price|cost)?\s*"
    r"(?:is|:|-)?\s*(?:₹|\bINR\b|\bRs\.?)\s*"
    r"(\d[\d,]*(?:\.\d{1,2})?)",
    flags=re.IGNORECASE,
)
_HOURS_PATTERN = re.compile(
    r"\b(?:open(?:ing)?\s+hours?\s*[:\-]?\s*)?"
    r"(\d{1,2}(?::[0-5]\d)?\s*(?:a\.?m\.?|p\.?m\.?))"
    r"\s*(?:-|–|—|to)\s*"
    r"(\d{1,2}(?::[0-5]\d)?\s*(?:a\.?m\.?|p\.?m\.?))\b",
    flags=re.IGNORECASE,
)


class _TavilyResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = ""
    url: str | None = None
    content: str = ""


class _TavilyResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    results: list[_TavilyResult]


_ATTRACTION_LIST = TypeAdapter(list[AttractionOption])
_HTTP_URL = TypeAdapter(HttpUrl)


class TavilyAttractionsProvider:
    """Tavily-backed attraction suggestions with deterministic data extraction."""

    def __init__(
        self,
        settings: Settings,
        redis: Redis,
        *,
        fetched_at: datetime,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.settings = settings
        self.redis = redis
        self.fetched_at = fetched_at
        self.client = client
        self._sleep = sleep
        self._base_url = validate_external_base_url(
            settings.tavily_base_url,
            allowed_hosts=settings.tavily_host_allowlist,
        )

    async def attractions(self, requirements: TripRequirements) -> list[AttractionOption]:
        destinations = list(
            dict.fromkeys(
                destination
                for destination in requirements.destinations
                if destination != requirements.origin
            )
        )
        if not destinations:
            return []
        if not self.settings.tavily_configured:
            return [self._fallback(destination) for destination in destinations]

        searches_used = 0
        attractions: list[AttractionOption] = []
        for destination in destinations:
            cached = await self._read_cache(destination)
            if cached is not None:
                attractions.extend(cached)
                continue
            if searches_used >= self.settings.tavily_max_searches_per_trip:
                attractions.append(self._fallback(destination))
                continue

            searches_used += 1
            payload = await self._search(destination)
            if payload is None:
                attractions.append(self._fallback(destination))
                continue
            parsed = self._extract(destination, payload)
            if not parsed:
                attractions.append(self._fallback(destination))
                continue
            attractions.extend(parsed)
            await self._write_cache(destination, parsed)
        return attractions

    async def _search(self, city: str) -> _TavilyResponse | None:
        api_key = self.settings.tavily_api_key
        if api_key is None:
            return None
        safe_city = self._city_for_query(city)
        if not safe_city:
            return None
        headers = {
            "Authorization": f"Bearer {api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }
        body = {
            "query": f"top tourist attractions in {safe_city}",
            "search_depth": "basic",
            "topic": "general",
            "max_results": MAX_RESULTS,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
        }
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = await self._send(headers=headers, body=body)
                if response.status_code in {432, 433}:
                    self._log_failure("TavilyCreditsExhausted", response.status_code)
                    return None
                response.raise_for_status()
                return _TavilyResponse.model_validate(response.json())
            except Exception as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                retryable = not isinstance(exc, httpx.HTTPStatusError) or (
                    status == 429 or (status is not None and status >= 500)
                )
                if attempt >= MAX_RETRIES or not retryable:
                    self._log_failure(type(exc).__name__, status)
                    return None
                await self._sleep(RETRY_BACKOFF_SECONDS * (2**attempt))
        return None

    async def _send(
        self, *, headers: dict[str, str], body: dict[str, Any]
    ) -> httpx.Response:
        url = f"{self._base_url}/search"
        if self.client is not None:
            return await self.client.post(
                url,
                headers=headers,
                json=body,
                timeout=self.settings.tavily_timeout_seconds,
            )
        async with httpx.AsyncClient() as client:
            return await client.post(
                url,
                headers=headers,
                json=body,
                timeout=self.settings.tavily_timeout_seconds,
            )

    def _extract(
        self, destination: str, payload: _TavilyResponse
    ) -> list[AttractionOption]:
        items: list[AttractionOption] = []
        for result in payload.results:
            source_url_text = self._safe_source_url(result.url)
            if source_url_text is None:
                continue
            name = self._clean_text(result.title, limit=200)
            if not name:
                continue
            description = self._clean_text(result.content, limit=1000)
            amount = self._parse_fee(result.content)
            opening_hours = self._parse_opening_hours(result.content)
            source_domain = (
                urlsplit(source_url_text).hostname or ""
            ).casefold().rstrip(".")
            try:
                source_url = _HTTP_URL.validate_python(source_url_text)
                items.append(
                    AttractionOption(
                        destination=destination,
                        name=name,
                        description=(
                            description or "Source page contains the attraction details."
                        ),
                        entry_fee=PriceQuote(
                            amount=amount,
                            price_type="estimate" if amount is not None else "unknown",
                            source=source_url_text,
                            fetched_at=self.fetched_at,
                        ),
                        opening_hours=opening_hours,
                        source_url=source_url,
                        source_domain=source_domain,
                        fetched_at=self.fetched_at,
                    )
                )
            except (ValidationError, ValueError):
                continue
        return items

    async def _read_cache(self, city: str) -> list[AttractionOption] | None:
        key = self._cache_key(city)
        try:
            cached = await self.redis.get(key)
        except Exception as exc:
            logger.warning(
                "Tavily attraction cache read failed",
                extra={"error_type": type(exc).__name__},
            )
            return None
        if cached is None:
            return None
        try:
            return _ATTRACTION_LIST.validate_json(cached)
        except ValidationError:
            with suppress(Exception):
                await self.redis.delete(key)
            return None

    async def _write_cache(self, city: str, items: list[AttractionOption]) -> None:
        try:
            await self.redis.set(
                self._cache_key(city),
                _ATTRACTION_LIST.dump_json(items),
                ex=self.settings.tavily_cache_ttl_seconds,
            )
        except Exception as exc:
            logger.warning(
                "Tavily attraction cache write failed",
                extra={"error_type": type(exc).__name__},
            )

    def _fallback(self, destination: str) -> AttractionOption:
        return AttractionOption(
            destination=destination,
            name=f"Stub attraction in {destination}",
            description="Placeholder only; Tavily attraction research is unavailable.",
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

    @staticmethod
    def _clean_text(value: str, *, limit: int) -> str:
        return " ".join(value.replace("\x00", " ").split())[:limit]

    @staticmethod
    def _city_for_query(value: str) -> str:
        characters: list[str] = []
        for character in " ".join(value.split())[:100]:
            if character.isalpha() or character in {" ", "-", "'", "."}:
                characters.append(character)
                continue
            break
        return "".join(characters).strip(" .-'")

    @staticmethod
    def _parse_fee(text: str) -> Decimal | None:
        match = _FEE_PATTERN.search(text)
        if match is None:
            return None
        try:
            return Decimal(match.group(1).replace(",", ""))
        except InvalidOperation:
            return None

    @staticmethod
    def _parse_opening_hours(text: str) -> str | None:
        match = _HOURS_PATTERN.search(text)
        if match is None:
            return None
        return " - ".join(" ".join(value.split()) for value in match.groups())

    @staticmethod
    def _safe_source_url(value: str | None) -> str | None:
        if not value:
            return None
        parsed = urlsplit(value.strip())
        if parsed.scheme.casefold() != "https" or parsed.username or parsed.password:
            return None
        hostname = (parsed.hostname or "").casefold().rstrip(".")
        if not hostname or hostname == "localhost" or hostname.endswith(
            (".localhost", ".local", ".internal")
        ):
            return None
        try:
            address = ip_address(hostname)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            return None
        return value.strip()

    @staticmethod
    def _log_failure(error_type: str, http_status: int | None) -> None:
        logger.warning(
            "Tavily attraction search failed; using stub fallback",
            extra={"error_type": error_type, "http_status": http_status},
        )

    @staticmethod
    def _cache_key(city: str) -> str:
        digest = hashlib.sha256(city.casefold().strip().encode("utf-8")).hexdigest()
        return f"devsafar:tavily:attractions:v1:{digest}"
