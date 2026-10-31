import asyncio
import difflib
import hashlib
import html
import logging
import re
import unicodedata
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, HttpUrl, TypeAdapter, ValidationError
from redis.asyncio import Redis

from app.agents.llm import AttractionExtractionFailure, AttractionExtractor
from app.core.config import Settings
from app.core.logging import current_request_id
from app.schemas.attraction import AttractionCandidate, AttractionOption
from app.schemas.common import PriceQuote
from app.schemas.trip import TripRequirements
from app.utils.url_validator import (
    validate_external_base_url,
    validate_public_https_url,
)

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
_OPEN_FROM_PATTERN = re.compile(
    r"\bopen(?:s)?\s+from\s+"
    r"(\d{1,2}:[0-5]\d\s*(?:a\.?m\.?|p\.?m\.?)?)"
    r"\s*(?:-|–|—|to)\s*"
    r"(\d{1,2}:[0-5]\d\s*(?:a\.?m\.?|p\.?m\.?)?)\b",
    flags=re.IGNORECASE,
)
_OPENS_AT_PATTERN = re.compile(
    r"\bopens\s+at\s+(\d{1,2}:[0-5]\d\s*(?:a\.?m\.?|p\.?m\.?)?)\b",
    flags=re.IGNORECASE,
)
_MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
_RAW_URL_PATTERN = re.compile(r"https?://\S+", flags=re.IGNORECASE)
_PAGE_TITLE_PHRASES = (
    "places to visit",
    "things to do",
    "tourism in",
    "travel guide",
    "tourist attractions in",
    "wikipedia",
    "youtube",
)
_INSTRUCTION_PHRASES = (
    "ignore all",
    "ignore previous",
    "system prompt",
    "follow these instructions",
    "return fake",
    "call a tool",
)


class _TavilyResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = ""
    url: str | None = None
    content: str = ""


class _TavilyResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    results: list[_TavilyResult]


@dataclass(frozen=True, slots=True)
class _SourceSnippet:
    title: str
    url: str
    domain: str
    content: str


@dataclass(slots=True)
class _ExternalCallCounts:
    tavily_searches: int = 0
    groq_calls: int = 0


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
        extractor: AttractionExtractor,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.settings = settings
        self.redis = redis
        self.fetched_at = fetched_at
        self.extractor = extractor
        self.client = client
        self._sleep = sleep
        self._base_url = validate_external_base_url(
            settings.tavily_base_url,
            allowed_hosts=settings.tavily_host_allowlist,
        )

    async def attractions(self, requirements: TripRequirements) -> list[AttractionOption]:
        counts = _ExternalCallCounts()
        try:
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
                if await self._negative_cache_hit(destination):
                    attractions.append(self._fallback(destination))
                    continue
                if searches_used >= self.settings.tavily_max_searches_per_trip:
                    attractions.append(self._fallback(destination))
                    continue

                searches_used += 1
                payload, search_calls = await self._search(destination)
                counts.tavily_searches += search_calls
                if payload is None:
                    await self._write_negative_cache(destination)
                    attractions.append(self._fallback(destination))
                    continue
                snippets = self._prepare_snippets(payload)
                if not snippets:
                    await self._write_negative_cache(destination)
                    attractions.append(self._fallback(destination))
                    continue
                try:
                    extraction = await self.extractor.extract_attractions(
                        city=destination,
                        snippets=[snippet.content for snippet in snippets],
                    )
                    counts.groq_calls += extraction.external_calls
                except AttractionExtractionFailure as exc:
                    counts.groq_calls += exc.external_calls
                    await self._write_negative_cache(destination)
                    attractions.append(self._fallback(destination))
                    continue
                except Exception as exc:
                    counts.groq_calls += int(getattr(exc, "external_calls", 0))
                    logger.warning(
                        "Unexpected attraction extractor failure; using stub fallback",
                        extra={
                            "request_id": current_request_id(),
                            "error_type": type(exc).__name__,
                        },
                    )
                    await self._write_negative_cache(destination)
                    attractions.append(self._fallback(destination))
                    continue
                grounded = self._ground_candidates(
                    destination,
                    extraction.candidates,
                    snippets,
                )
                if not grounded:
                    await self._write_negative_cache(destination)
                    attractions.append(self._fallback(destination))
                    continue
                attractions.extend(grounded)
                await self._write_cache(destination, grounded)
            return attractions
        finally:
            logger.info(
                "Attraction external call counts",
                extra={
                    "request_id": current_request_id(),
                    "groq_calls": counts.groq_calls,
                    "tavily_searches": counts.tavily_searches,
                },
            )

    async def _search(self, city: str) -> tuple[_TavilyResponse | None, int]:
        api_key = self.settings.tavily_api_key
        if api_key is None:
            return None, 0
        safe_city = self._city_for_query(city)
        if not safe_city:
            return None, 0
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
            "exclude_domains": sorted(self.settings.tavily_excluded_domain_set),
        }
        calls = 0
        for attempt in range(MAX_RETRIES + 1):
            try:
                calls += 1
                response = await self._send(headers=headers, body=body)
                if response.status_code in {432, 433}:
                    self._log_failure("TavilyCreditsExhausted", response.status_code)
                    return None, calls
                response.raise_for_status()
                return _TavilyResponse.model_validate(response.json()), calls
            except Exception as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                retryable = not isinstance(exc, httpx.HTTPStatusError) or (
                    status == 429 or (status is not None and status >= 500)
                )
                if attempt >= MAX_RETRIES or not retryable:
                    self._log_failure(type(exc).__name__, status)
                    return None, calls
                await self._sleep(RETRY_BACKOFF_SECONDS * (2**attempt))
        return None, calls

    async def _send(self, *, headers: dict[str, str], body: dict[str, Any]) -> httpx.Response:
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

    def _eligible_snippets(self, payload: _TavilyResponse) -> list[_SourceSnippet]:
        snippets: list[_SourceSnippet] = []
        excluded = self.settings.tavily_excluded_domain_set
        for result in payload.results:
            if not result.url or not result.content.strip():
                continue
            try:
                source_url = validate_public_https_url(result.url)
            except ValueError:
                continue
            domain = (urlsplit(source_url).hostname or "").casefold().rstrip(".")
            if any(domain == blocked or domain.endswith(f".{blocked}") for blocked in excluded):
                continue
            snippets.append(
                _SourceSnippet(
                    title=result.title,
                    url=source_url,
                    domain=domain,
                    content=result.content,
                )
            )
        return snippets

    def _prepare_snippets(self, payload: _TavilyResponse) -> list[_SourceSnippet]:
        eligible = self._eligible_snippets(payload)
        selected: list[_SourceSnippet] = []
        fingerprints: list[str] = []
        near_empty_count = 0
        duplicate_count = 0
        truncated_count = 0
        for snippet in eligible:
            normalized_content = " ".join(snippet.content.split())
            if len(normalized_content) < 40:
                near_empty_count += 1
                continue
            fingerprint = self._normalize_for_grounding(normalized_content)
            if any(
                fingerprint == existing
                or difflib.SequenceMatcher(None, fingerprint, existing).ratio() >= 0.9
                for existing in fingerprints
            ):
                duplicate_count += 1
                continue
            if len(normalized_content) > self.settings.attraction_snippet_max_chars:
                normalized_content = normalized_content[
                    : self.settings.attraction_snippet_max_chars
                ].rstrip()
                truncated_count += 1
            selected.append(
                _SourceSnippet(
                    title=snippet.title,
                    url=snippet.url,
                    domain=snippet.domain,
                    content=normalized_content,
                )
            )
            fingerprints.append(fingerprint)
            if len(selected) >= self.settings.tavily_snippets_for_extraction:
                break
        logger.info(
            "Prepared Tavily snippets for attraction extraction",
            extra={
                "request_id": current_request_id(),
                "result_count": len(payload.results),
                "eligible_count": len(eligible),
                "selected_count": len(selected),
                "near_empty_count": near_empty_count,
                "duplicate_count": duplicate_count,
                "truncated_count": truncated_count,
            },
        )
        return selected

    def _ground_candidates(
        self,
        destination: str,
        candidates: list[AttractionCandidate],
        snippets: list[_SourceSnippet],
    ) -> list[AttractionOption]:
        items: list[AttractionOption] = []
        seen_names: set[str] = set()
        title_names = {self._normalize_for_grounding(snippet.title) for snippet in snippets}
        for candidate in candidates:
            name = self._clean_plain_text(candidate.name, limit=120)
            normalized_name = self._normalize_for_grounding(name)
            if (
                not normalized_name
                or normalized_name in seen_names
                or normalized_name in title_names
                or self._looks_like_page_title(name)
            ):
                continue
            grounded = self._find_grounded_snippet(
                normalized_name=normalized_name,
                evidence_quote=candidate.evidence_quote,
                snippets=snippets,
            )
            if grounded is None:
                continue
            snippet, evidence_sentence = grounded
            description = self._clean_plain_text(evidence_sentence, limit=200)
            if not description:
                continue
            amount = self._parse_fee(evidence_sentence)
            opening_hours = self._parse_opening_hours(evidence_sentence)
            extra_urls: list[str] = []
            for other in snippets:
                if (
                    other.url == snippet.url
                    or other.url in extra_urls
                    or normalized_name not in self._normalize_for_grounding(other.content)
                ):
                    continue
                extra_urls.append(other.url)
                if len(extra_urls) == 2:
                    break
            try:
                source_url = _HTTP_URL.validate_python(snippet.url)
                items.append(
                    AttractionOption(
                        destination=destination,
                        name=name,
                        category=candidate.category,
                        description=description,
                        entry_fee=PriceQuote(
                            amount=amount,
                            price_type="estimate" if amount is not None else "unknown",
                            source=snippet.url,
                            fetched_at=self.fetched_at,
                        ),
                        opening_hours=opening_hours,
                        source_url=source_url,
                        additional_source_urls=[
                            _HTTP_URL.validate_python(url) for url in extra_urls
                        ],
                        source_domain=snippet.domain,
                        fetched_at=self.fetched_at,
                    )
                )
            except (ValidationError, ValueError):
                continue
            seen_names.add(normalized_name)
            if len(items) >= self.settings.attractions_per_destination:
                break
        return items

    @classmethod
    def _find_grounded_snippet(
        cls,
        *,
        normalized_name: str,
        evidence_quote: str,
        snippets: list[_SourceSnippet],
    ) -> tuple[_SourceSnippet, str] | None:
        for snippet in snippets:
            if evidence_quote not in snippet.content:
                continue
            if normalized_name not in cls._normalize_for_grounding(snippet.content):
                continue
            if normalized_name not in cls._normalize_for_grounding(evidence_quote):
                continue
            if any(phrase in evidence_quote.casefold() for phrase in _INSTRUCTION_PHRASES):
                continue
            return snippet, evidence_quote.strip()
        return None

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
        finally:
            with suppress(Exception):
                await self.redis.delete(self._negative_cache_key(city))

    async def _negative_cache_hit(self, city: str) -> bool:
        try:
            return bool(await self.redis.get(self._negative_cache_key(city)))
        except Exception as exc:
            logger.warning(
                "Tavily attraction negative cache read failed",
                extra={"error_type": type(exc).__name__},
            )
            return False

    async def _write_negative_cache(self, city: str) -> None:
        try:
            await self.redis.set(
                self._negative_cache_key(city),
                b"1",
                ex=self.settings.tavily_negative_cache_ttl_seconds,
            )
        except Exception as exc:
            logger.warning(
                "Tavily attraction negative cache write failed",
                extra={"error_type": type(exc).__name__},
            )

    def _fallback(self, destination: str) -> AttractionOption:
        return AttractionOption(
            destination=destination,
            name=f"Stub attraction in {destination}",
            description="Attraction research unavailable for this destination right now.",
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
    def _clean_plain_text(value: str, *, limit: int) -> str:
        cleaned = html.unescape(value.replace("\x00", " "))
        cleaned = _MARKDOWN_IMAGE_PATTERN.sub(r"\1", cleaned)
        cleaned = _MARKDOWN_LINK_PATTERN.sub(r"\1", cleaned)
        cleaned = _HTML_TAG_PATTERN.sub(" ", cleaned)
        cleaned = _RAW_URL_PATTERN.sub(" ", cleaned)
        cleaned = re.sub(r"[`*_~#>|]+", " ", cleaned)
        cleaned = "".join(
            character
            for character in cleaned
            if unicodedata.category(character) not in {"So", "Sk", "Cs", "Cf"}
        )
        cleaned = " ".join(cleaned.split())
        cleaned = re.sub(r"\s+([.,;:!?])", r"\1", cleaned)
        return cleaned[:limit].strip()

    @staticmethod
    def _normalize_for_grounding(value: str) -> str:
        return "".join(
            character for character in html.unescape(value).casefold() if character.isalnum()
        )

    @staticmethod
    def _looks_like_page_title(name: str) -> bool:
        lowered = name.casefold()
        return any(phrase in lowered for phrase in _PAGE_TITLE_PHRASES) or bool(
            re.match(r"^\d+\s+", name)
        )

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
        range_match = _OPEN_FROM_PATTERN.search(text)
        if range_match is not None:
            return " - ".join(" ".join(value.split()) for value in range_match.groups())
        at_match = _OPENS_AT_PATTERN.search(text)
        if at_match is not None:
            return f"Opens at {' '.join(at_match.group(1).split())}"
        return None

    @staticmethod
    def _log_failure(error_type: str, http_status: int | None) -> None:
        logger.warning(
            "Tavily attraction search failed; using stub fallback",
            extra={"error_type": error_type, "http_status": http_status},
        )

    @staticmethod
    def _cache_key(city: str) -> str:
        digest = hashlib.sha256(city.casefold().strip().encode("utf-8")).hexdigest()
        return f"devsafar:tavily:attractions:v2:{digest}"

    @staticmethod
    def _negative_cache_key(city: str) -> str:
        digest = hashlib.sha256(city.casefold().strip().encode("utf-8")).hexdigest()
        return f"devsafar:tavily:attractions:v2:negative:{digest}"
