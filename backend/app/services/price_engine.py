import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from statistics import median
from typing import Any, Literal
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.integrations.base import ProviderFailure
from app.integrations.serpapi_flights import FlightProviderResult, SerpApiFlightsProvider
from app.integrations.serpapi_hotels import SerpApiHotelsProvider
from app.repositories.price_history_repository import (
    PriceHistoryRepository,
    PriceHistoryWrite,
)
from app.schemas.common import DataSource, PriceQuote
from app.schemas.hotel import HotelOption
from app.schemas.transport import RouteLeg, TransportOption
from app.schemas.trip import ModeComparison, TripRequirements
from app.services.fare_estimator import FareEstimatePlan, FareEstimator

logger = logging.getLogger(__name__)
BookingBucket = Literal["same_day", "1_7_days", "8_30_days", "31_plus"]
QUOTA_WARNING = "Live fare search budget reached; showing previous or estimated values."
NO_MATCH_NOTE = "No matching service for the searched date"


@dataclass(frozen=True, slots=True)
class PriceQuery:
    mode: str
    origin_code: str | None
    destination_code: str
    travel_date: date
    cabin_or_class: str
    passengers: int
    nights: int | None
    price_unit: str

    def booking_bucket(self, observed_at: datetime) -> BookingBucket:
        days = max(0, (self.travel_date - observed_at.date()).days)
        if days == 0:
            return "same_day"
        if days <= 7:
            return "1_7_days"
        if days <= 30:
            return "8_30_days"
        return "31_plus"

    def context(self) -> str:
        date_dimension = (
            ("weekend" if self.travel_date.weekday() >= 5 else "weekday")
            if self.mode == "flight"
            else (
                self.travel_date.isoformat()
                if self.mode == "hotel"
                else (
                    f"{self.travel_date.isocalendar().year}-"
                    f"W{self.travel_date.isocalendar().week:02d}"
                )
            )
        )
        raw = json.dumps(
            {
                "mode": self.mode,
                "origin": self.origin_code,
                "destination": self.destination_code,
                "class": self.cabin_or_class,
                "passengers": self.passengers,
                "nights": self.nights,
                "date_dimension": date_dimension,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(raw.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ResolvedPrice:
    quote: PriceQuote
    tried: tuple[str, ...]
    warning: str | None = None


class SerpApiQuota:
    _SCRIPT = """
local monthly = tonumber(redis.call('GET', KEYS[1]) or '0')
local trip = tonumber(redis.call('GET', KEYS[2]) or '0')
if monthly >= tonumber(ARGV[1]) then return 0 end
if trip >= tonumber(ARGV[2]) then return 1 end
redis.call('INCR', KEYS[1])
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[3]))
redis.call('INCR', KEYS[2])
redis.call('EXPIRE', KEYS[2], tonumber(ARGV[4]))
return 2
"""

    def __init__(self, redis: Redis, settings: Settings) -> None:
        self.redis = redis
        self.settings = settings

    async def reserve(self, trip_id: UUID, *, now: datetime) -> Literal["ok", "monthly", "trip"]:
        month_key = f"price:serpapi:month:{now:%Y-%m}"
        trip_key = f"price:serpapi:trip:{trip_id}"
        result = int(
            await self.redis.eval(
                self._SCRIPT,
                2,
                month_key,
                trip_key,
                self.settings.serpapi_monthly_budget,
                self.settings.serpapi_max_searches_per_trip,
                40 * 24 * 3600,
                24 * 3600,
            )
        )
        logger.info("SerpApi search counter checked", extra={"quota_result": result})
        return "monthly" if result == 0 else "trip" if result == 1 else "ok"


class PriceEngine:
    def __init__(
        self,
        settings: Settings,
        redis: Redis,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        flights: SerpApiFlightsProvider | None = None,
        hotels: SerpApiHotelsProvider | None = None,
        now_provider: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.settings = settings
        self.redis = redis
        self.session_factory = session_factory
        self.flights = flights
        self.hotels = hotels
        self.quota = SerpApiQuota(redis, settings)
        self.now_provider = now_provider

    async def enrich_plan(
        self,
        *,
        trip_id: UUID,
        requirements: TripRequirements,
        plan: FareEstimatePlan,
        persist_history: bool = True,
    ) -> tuple[FareEstimatePlan, list[DataSource], list[str]]:
        flight_options = [item for item in plan.transport_options if item.mode == "flight"]
        other_options = [item for item in plan.transport_options if item.mode != "flight"]
        enriched_flights, flight_tried, warnings = await self._enrich_flights(
            trip_id=trip_id,
            requirements=requirements,
            options=flight_options,
            persist_history=persist_history,
        )
        enriched_hotels, hotel_tried, hotel_warnings = await self._enrich_hotels(
            trip_id=trip_id,
            requirements=requirements,
            formulas=plan.hotels,
            persist_history=persist_history,
        )
        warnings.extend(hotel_warnings)
        hotel_min, hotel_max = _hotel_bounds(enriched_hotels, plan)
        comparisons = [
            self._flight_comparison(
                item,
                enriched_flights,
                requirements=requirements,
                hotel_min=hotel_min,
                hotel_max=hotel_max,
                plan=plan,
            )
            if item.mode == "flight"
            else item
            for item in plan.mode_comparison
        ]
        route_legs = self._replace_selected_flight_legs(plan.route_legs, enriched_flights)
        enriched_plan = replace(
            plan,
            route_legs=route_legs,
            transport_options=[*other_options, *enriched_flights],
            hotels=enriched_hotels,
            mode_comparison=comparisons,
            hotel_total_min=hotel_min,
            hotel_total_max=hotel_max,
        )
        sources = [
            DataSource(
                name="serpapi_flights",
                price_type=_source_price_type(enriched_flights),
                fetched_at=self.now_provider(),
                status=("ok" if any(x.price.status == "live_search_result" for x in enriched_flights) else "degraded"),
                providers_tried=list(dict.fromkeys(flight_tried)),
            ),
            DataSource(
                name="serpapi_hotels",
                price_type=_hotel_source_price_type(enriched_hotels),
                fetched_at=self.now_provider(),
                status=("ok" if any(x.total_price.status == "live_search_result" for x in enriched_hotels) else "degraded"),
                providers_tried=list(dict.fromkeys(hotel_tried)),
            ),
        ]
        return enriched_plan, sources, list(dict.fromkeys(warnings))

    async def _enrich_flights(
        self,
        *,
        trip_id: UUID,
        requirements: TripRequirements,
        options: list[TransportOption],
        persist_history: bool,
    ) -> tuple[list[TransportOption], list[str], list[str]]:
        if not options:
            return [], [], []
        dates = FareEstimator.approximate_leg_dates(requirements, len(options))
        enriched: list[TransportOption] = []
        all_tried: list[str] = []
        warnings: list[str] = []
        for option, travel_date in zip(options, dates, strict=True):
            query = PriceQuery(
                mode="flight",
                origin_code=FareEstimator.airport_code(option.origin),
                destination_code=FareEstimator.airport_code(option.destination) or option.destination,
                travel_date=travel_date,
                cabin_or_class="economy",
                passengers=requirements.travelers,
                nights=None,
                price_unit="one adult one-way",
            )
            resolved, provider_result = await self._resolve_flight(
                trip_id=trip_id,
                query=query,
                formula=option.price,
                persist_history=persist_history,
            )
            all_tried.extend(resolved.tried)
            if resolved.warning:
                warnings.append(resolved.warning)
            enriched.append(
                option.model_copy(
                    update={
                        "provider": resolved.quote.provider,
                        "duration_minutes": (
                            provider_result.total_duration_minutes
                            if provider_result is not None
                            else option.duration_minutes
                        ),
                        "duration_minutes_min": (
                            provider_result.total_duration_minutes
                            if provider_result is not None
                            and provider_result.total_duration_minutes is not None
                            else option.duration_minutes_min
                        ),
                        "duration_minutes_max": (
                            provider_result.total_duration_minutes
                            if provider_result is not None
                            and provider_result.total_duration_minutes is not None
                            else option.duration_minutes_max
                        ),
                        "price": resolved.quote,
                        "availability": (
                            "unavailable"
                            if resolved.quote.status == "unavailable"
                            else "available"
                            if resolved.quote.status == "live_search_result"
                            else "unknown"
                        ),
                        "note": resolved.quote.note,
                        "alternatives": list(provider_result.alternatives) if provider_result else [],
                    }
                )
            )
        return enriched, all_tried, warnings

    async def _resolve_flight(
        self,
        *,
        trip_id: UUID,
        query: PriceQuery,
        formula: PriceQuote,
        persist_history: bool = True,
    ) -> tuple[ResolvedPrice, FlightProviderResult | None]:
        tried: list[str] = ["redis_cache"]
        cache_key = _cache_key("flight", query)
        cached = await self._read_cache(cache_key)
        if cached is not None:
            result = FlightProviderResult(
                amount=Decimal(cached["amount"]),
                observed_at=datetime.fromisoformat(cached["observed_at"]),
                total_duration_minutes=cached.get("total_duration_minutes"),
                alternatives=(),
            )
            return (
                ResolvedPrice(
                    quote=_previous_quote(
                        amount=result.amount,
                        provider="SerpApi Google Flights",
                        observed_at=result.observed_at,
                        price_unit=query.price_unit,
                        note="Cached search result; search result, not a confirmed booking",
                    ),
                    tried=tuple(tried),
                ),
                result,
            )
        provider_failure: str | None = None
        if query.origin_code is None or len(query.destination_code) != 3:
            provider_failure = "unknown_airport"
        elif self.flights is None or not self.settings.serpapi_configured:
            provider_failure = "disabled_or_missing_key"
        else:
            quota = await self.quota.reserve(trip_id, now=self.now_provider())
            if quota != "ok":
                provider_failure = "quota"
            else:
                tried.append("SerpApi Google Flights")
                try:
                    result = await self.flights.search_one_way(
                        departure_id=query.origin_code,
                        arrival_id=query.destination_code,
                        outbound_date=query.travel_date,
                        adults=1,
                    )
                    if result.empty:
                        quote = _unavailable_quote(
                            provider="SerpApi Google Flights",
                            observed_at=result.observed_at,
                            price_unit=query.price_unit,
                        )
                        return ResolvedPrice(quote=quote, tried=tuple(tried)), result
                    assert result.amount is not None
                    quote = _live_quote(
                        amount=result.amount,
                        provider="SerpApi Google Flights",
                        observed_at=result.observed_at,
                        price_unit=query.price_unit,
                    )
                    await self._write_cache(
                        cache_key,
                        {
                            "amount": str(result.amount),
                            "observed_at": result.observed_at.isoformat(),
                            "total_duration_minutes": result.total_duration_minutes,
                        },
                        ttl=self.settings.flight_cache_ttl_seconds,
                    )
                    if persist_history:
                        await self._store_history(query, quote)
                    return ResolvedPrice(quote=quote, tried=tuple(tried)), result
                except ProviderFailure as exc:
                    provider_failure = exc.code
        tried.append(f"live_failed:{provider_failure}")
        fallback = await self._history_or_formula(query, formula=formula, tried=tried)
        warning = QUOTA_WARNING if provider_failure == "quota" else None
        return replace(fallback, warning=warning), None

    async def _enrich_hotels(
        self,
        *,
        trip_id: UUID,
        requirements: TripRequirements,
        formulas: list[HotelOption],
        persist_history: bool,
    ) -> tuple[list[HotelOption], list[str], list[str]]:
        if not formulas:
            return [], [], []
        grouped: dict[tuple[str, date, date], list[HotelOption]] = {}
        for item in formulas:
            grouped.setdefault((item.destination, item.check_in, item.check_out), []).append(item)
        results: list[HotelOption] = []
        tried_all: list[str] = []
        warnings: list[str] = []
        for (destination, check_in, check_out), formula_group in grouped.items():
            group, tried, warning = await self._resolve_hotel_group(
                trip_id=trip_id,
                destination=destination,
                check_in=check_in,
                check_out=check_out,
                travelers=requirements.travelers,
                formulas=formula_group,
                persist_history=persist_history,
            )
            results.extend(group)
            tried_all.extend(tried)
            if warning:
                warnings.append(warning)
        return results, tried_all, warnings

    async def _resolve_hotel_group(
        self,
        *,
        trip_id: UUID,
        destination: str,
        check_in: date,
        check_out: date,
        travelers: int,
        formulas: list[HotelOption],
        persist_history: bool,
    ) -> tuple[list[HotelOption], list[str], str | None]:
        nights = max(1, (check_out - check_in).days)
        cache_query = PriceQuery(
            mode="hotel",
            origin_code=None,
            destination_code=destination.casefold(),
            travel_date=check_in,
            cabin_or_class="all_tiers",
            passengers=travelers,
            nights=nights,
            price_unit="one room, full stay",
        )
        tried = ["redis_cache"]
        cached = await self._read_cache(_cache_key("hotel", cache_query))
        if cached is not None:
            observed_at = datetime.fromisoformat(str(cached["observed_at"]))
            cached_options: list[HotelOption] = []
            for item in cached.get("options", []):
                note = (
                    "Cached hotel search result; search result, not a confirmed booking"
                )
                cached_options.append(
                    HotelOption(
                        destination=destination,
                        name=str(item["name"]),
                        check_in=check_in,
                        check_out=check_out,
                        nightly_price=_previous_quote(
                            amount=Decimal(str(item["nightly_amount"])),
                            provider="SerpApi Google Hotels",
                            observed_at=observed_at,
                            price_unit="one room per night",
                            note=note,
                        ),
                        total_price=_previous_quote(
                            amount=Decimal(str(item["total_amount"])),
                            provider="SerpApi Google Hotels",
                            observed_at=observed_at,
                            price_unit="one room, full stay",
                            note=note,
                        ),
                        availability="unknown",
                        tier=item.get("tier"),
                        note=note,
                    )
                )
            if cached_options:
                return cached_options, tried, None
        provider_failure: str | None = None
        if self.hotels is None or not self.settings.serpapi_configured:
            provider_failure = "disabled_or_missing_key"
        else:
            quota = await self.quota.reserve(trip_id, now=self.now_provider())
            if quota != "ok":
                provider_failure = "quota"
            else:
                tried.append("SerpApi Google Hotels")
                try:
                    provider_result = await self.hotels.search(
                        city=destination,
                        check_in=check_in,
                        check_out=check_out,
                        adults=travelers,
                    )
                    if provider_result.empty:
                        unavailable = _unavailable_quote(
                            provider="SerpApi Google Hotels",
                            observed_at=provider_result.observed_at,
                            price_unit="one room, full stay",
                        )
                        return [
                            HotelOption(
                                destination=destination,
                                name="No matching property in search results",
                                check_in=check_in,
                                check_out=check_out,
                                nightly_price=unavailable.model_copy(
                                    update={"price_unit": "one room per night"}
                                ),
                                total_price=unavailable,
                                availability="unavailable",
                                note=NO_MATCH_NOTE,
                            )
                        ], tried, None
                    live_options: list[HotelOption] = []
                    for option in provider_result.options:
                        note = "lowest listed property in search results (an example, not a guaranteed rate)"
                        if not option.includes_taxes_fees:
                            note += "; may exclude taxes and fees"
                        total_quote = _live_quote(
                            amount=option.total_amount,
                            provider="SerpApi Google Hotels",
                            observed_at=provider_result.observed_at,
                            price_unit="one room, full stay",
                            note=note,
                        )
                        nightly_quote = _live_quote(
                            amount=option.nightly_amount,
                            provider="SerpApi Google Hotels",
                            observed_at=provider_result.observed_at,
                            price_unit="one room per night",
                            note=note,
                        )
                        live_options.append(
                            HotelOption(
                                destination=destination,
                                name=option.name,
                                check_in=check_in,
                                check_out=check_out,
                                nightly_price=nightly_quote,
                                total_price=total_quote,
                                availability="available",
                                tier=option.tier,
                                note=note,
                            )
                        )
                        history_query = replace(
                            cache_query,
                            cabin_or_class=option.tier or "unclassified",
                        )
                        if persist_history:
                            await self._store_history(history_query, total_quote)
                    await self._write_cache(
                        _cache_key("hotel", cache_query),
                        {
                            "observed_at": provider_result.observed_at.isoformat(),
                            "options": [
                                {
                                    "name": item.name,
                                    "total_amount": str(item.total_amount),
                                    "nightly_amount": str(item.nightly_amount),
                                    "tier": item.tier,
                                }
                                for item in provider_result.options
                            ],
                        },
                        ttl=self.settings.hotel_cache_ttl_seconds,
                    )
                    return live_options, tried, None
                except ProviderFailure as exc:
                    provider_failure = exc.code
        tried.append(f"live_failed:{provider_failure}")
        fallbacks = await self._hotel_fallbacks(
            destination=destination,
            check_in=check_in,
            check_out=check_out,
            travelers=travelers,
            formulas=formulas,
            tried=tried,
        )
        return fallbacks, tried, QUOTA_WARNING if provider_failure == "quota" else None

    async def _hotel_fallbacks(
        self,
        *,
        destination: str,
        check_in: date,
        check_out: date,
        travelers: int,
        formulas: list[HotelOption],
        tried: list[str],
    ) -> list[HotelOption]:
        nights = max(1, (check_out - check_in).days)
        output: list[HotelOption] = []
        for formula in formulas:
            query = PriceQuery(
                mode="hotel",
                origin_code=None,
                destination_code=destination.casefold(),
                travel_date=check_in,
                cabin_or_class=formula.tier or "unclassified",
                passengers=travelers,
                nights=nights,
                price_unit="one room, full stay",
            )
            resolved = await self._history_or_formula(
                query,
                formula=formula.total_price,
                tried=tried,
            )
            total = resolved.quote
            nightly = _nightly_from_total(total, nights=nights)
            output.append(
                formula.model_copy(
                    update={
                        "total_price": total,
                        "nightly_price": nightly,
                        "availability": "unknown",
                        "note": total.note,
                    }
                )
            )
        return output

    async def _history_or_formula(
        self,
        query: PriceQuery,
        *,
        formula: PriceQuote,
        tried: list[str],
    ) -> ResolvedPrice:
        tried.append("price_history")
        now = self.now_provider()
        async with self.session_factory() as session:
            rows = await PriceHistoryRepository(session).comparable(
                context=query.context(),
                booking_bucket=query.booking_bucket(now),
                observed_after=now - timedelta(days=self.settings.price_history_max_age_days),
                now=now,
                allow_demo=self.settings.allow_demo_price_data,
            )
        if rows:
            values = [row.price for row in rows]
            if len(rows) <= 2:
                latest = rows[0]
                quote = _previous_quote(
                    amount=latest.price,
                    provider=latest.provider,
                    observed_at=latest.observed_at,
                    price_unit=latest.price_unit,
                    note=f"Previous comparable quote from {latest.observed_at.isoformat()}",
                    sample_count=len(rows),
                )
            else:
                quote = PriceQuote(
                    amount=Decimal(median(values)).quantize(Decimal("0.01")),
                    amount_min=min(values),
                    amount_max=max(values),
                    price_type="estimate",
                    source="price_history",
                    fetched_at=now,
                    status="estimated",
                    provider="price_history",
                    observed_at=max(row.observed_at for row in rows),
                    price_unit=query.price_unit,
                    sample_count=len(rows),
                    bookable=False,
                    note="Median of comparable historical provider search results",
                )
            return ResolvedPrice(quote=quote, tried=tuple(tried))
        tried.append("formula_estimate")
        if _quote_has_number(formula):
            return ResolvedPrice(
                quote=formula.model_copy(
                    update={
                        "status": "formula_estimate",
                        "price_type": "estimate",
                        "provider": formula.provider or formula.source,
                        "observed_at": now,
                        "bookable": False,
                        "sample_count": None,
                    }
                ),
                tried=tuple(tried),
            )
        return ResolvedPrice(
            quote=_unavailable_quote(
                provider="price_engine",
                observed_at=now,
                price_unit=query.price_unit,
                note="No live result, comparable history, or usable formula estimate",
            ),
            tried=tuple(tried),
        )

    async def _store_history(self, query: PriceQuery, quote: PriceQuote) -> None:
        if not self.settings.price_history_enabled or quote.status != "live_search_result":
            return
        if quote.amount is None or quote.currency != "INR":
            return
        observed_at = quote.observed_at
        async with self.session_factory() as session:
            await PriceHistoryRepository(session).add(
                PriceHistoryWrite(
                    context=query.context(),
                    mode=query.mode,
                    origin_code=query.origin_code,
                    destination_code=query.destination_code,
                    travel_date=query.travel_date,
                    observed_at=observed_at,
                    booking_bucket=query.booking_bucket(observed_at),
                    price=quote.amount,
                    currency=quote.currency,
                    provider=quote.provider,
                    price_unit=quote.price_unit,
                    cabin_or_class=query.cabin_or_class,
                    passengers=query.passengers,
                    nights=query.nights,
                    is_demo=False,
                    expires_at=observed_at
                    + timedelta(days=self.settings.price_history_retention_days),
                )
            )
            await session.commit()

    async def _read_cache(self, key: str) -> dict[str, Any] | None:
        try:
            raw = await self.redis.get(key)
            return json.loads(raw) if raw else None
        except Exception:
            logger.warning("Price cache read failed", extra={"cache_key_hash": key[-16:]})
            return None

    async def _write_cache(self, key: str, value: dict[str, Any], *, ttl: int) -> None:
        try:
            await self.redis.set(key, json.dumps(value, separators=(",", ":")), ex=ttl)
        except Exception:
            logger.warning("Price cache write failed", extra={"cache_key_hash": key[-16:]})

    @staticmethod
    def _replace_selected_flight_legs(
        legs: list[RouteLeg], flights: list[TransportOption]
    ) -> list[RouteLeg]:
        lookup = {(item.origin, item.destination): item for item in flights}
        output: list[RouteLeg] = []
        for leg in legs:
            option = lookup.get((leg.origin, leg.destination))
            if leg.mode == "flight" and option is not None:
                output.append(
                    leg.model_copy(
                        update={
                            "duration_minutes": option.duration_minutes,
                            "duration_minutes_min": option.duration_minutes_min,
                            "duration_minutes_max": option.duration_minutes_max,
                            "duration_source": option.provider,
                            "price": option.price,
                        }
                    )
                )
            else:
                output.append(leg)
        return output

    @staticmethod
    def _flight_comparison(
        original: ModeComparison,
        options: list[TransportOption],
        *,
        requirements: TripRequirements,
        hotel_min: Decimal,
        hotel_max: Decimal,
        plan: FareEstimatePlan,
    ) -> ModeComparison:
        bounds = [_price_bounds(item.price) for item in options]
        durations = [
            (
                item.duration_minutes_min
                if item.duration_minutes_min is not None
                else item.duration_minutes,
                item.duration_minutes_max
                if item.duration_minutes_max is not None
                else item.duration_minutes,
            )
            for item in options
        ]
        if not bounds or any(low is None or high is None for low, high in bounds):
            return original.model_copy(
                update={
                    "transport_price": options[0].price if len(options) == 1 else original.transport_price,
                    "notes": list(dict.fromkeys([*original.notes, *(x.note for x in options if x.note)])),
                }
            )
        low = sum((item[0] or Decimal("0") for item in bounds), Decimal("0"))
        high = sum((item[1] or Decimal("0") for item in bounds), Decimal("0"))
        low *= requirements.travelers
        high *= requirements.travelers
        duration_min = sum(item[0] or 0 for item in durations) if all(x[0] is not None for x in durations) else None
        duration_max = sum(item[1] or 0 for item in durations) if all(x[1] is not None for x in durations) else None
        live_only = all(item.price.status == "live_search_result" for item in options)
        if len(options) == 1 and requirements.travelers == 1 and live_only:
            transport_quote = options[0].price
        else:
            transport_quote = PriceQuote(
                amount_min=low,
                amount_max=high,
                price_type="estimate",
                source="price_engine",
                fetched_at=options[0].price.fetched_at,
                status="formula_estimate",
                provider="price_engine",
                observed_at=max(item.price.observed_at for item in options),
                price_unit=f"{requirements.travelers} traveller trip total",
                note="Planning total assembled from per-leg prices; not a confirmed booking",
            )
        total = PriceQuote(
            amount_min=low + hotel_min + plan.food_total_min + plan.local_transport_total_min,
            amount_max=high + hotel_max + plan.food_total_max + plan.local_transport_total_max,
            price_type="estimate",
            source="price_engine",
            fetched_at=transport_quote.fetched_at,
            status="formula_estimate",
            provider="price_engine",
            observed_at=transport_quote.observed_at,
            price_unit="trip total",
            note="Mixed planning total; provider search results are not confirmed bookings",
        )
        return original.model_copy(
            update={
                "duration_minutes_min": duration_min,
                "duration_minutes_max": duration_max,
                "transport_price": transport_quote,
                "total_price": total,
                "mixed_confidence": live_only,
                "notes": list(dict.fromkeys([*original.notes, *(x.note for x in options if x.note)])),
            }
        )


def _cache_key(kind: str, query: PriceQuery) -> str:
    digest = hashlib.sha256(
        json.dumps(
            {
                "kind": kind,
                "context": query.context(),
                "date": query.travel_date.isoformat(),
                "unit": query.price_unit,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return f"price:{kind}:v1:{digest}"


def _live_quote(
    *,
    amount: Decimal,
    provider: str,
    observed_at: datetime,
    price_unit: str,
    note: str = "search result, not a confirmed booking",
) -> PriceQuote:
    if "search result, not a confirmed booking" not in note.casefold():
        note = f"{note}; search result, not a confirmed booking"
    return PriceQuote(
        amount=amount,
        price_type="live_quote",
        source=provider,
        fetched_at=observed_at,
        status="live_search_result",
        provider=provider,
        observed_at=observed_at,
        price_unit=price_unit,
        bookable=False,
        note=note,
    )


def _previous_quote(
    *,
    amount: Decimal | None,
    provider: str,
    observed_at: datetime,
    price_unit: str,
    note: str,
    sample_count: int | None = None,
) -> PriceQuote:
    assert amount is not None
    return PriceQuote(
        amount=amount,
        price_type="estimate",
        source="price_history",
        fetched_at=datetime.now(UTC),
        status="previous",
        provider=provider,
        observed_at=observed_at,
        price_unit=price_unit,
        sample_count=sample_count,
        bookable=False,
        note=note,
    )


def _unavailable_quote(
    *,
    provider: str,
    observed_at: datetime,
    price_unit: str,
    note: str = NO_MATCH_NOTE,
) -> PriceQuote:
    return PriceQuote(
        amount=None,
        price_type="unknown",
        source=provider,
        fetched_at=observed_at,
        status="unavailable",
        provider=provider,
        observed_at=observed_at,
        price_unit=price_unit,
        bookable=False,
        note=note,
    )


def _quote_has_number(quote: PriceQuote) -> bool:
    return quote.amount is not None or (
        quote.amount_min is not None and quote.amount_max is not None
    )


def _price_bounds(quote: PriceQuote) -> tuple[Decimal | None, Decimal | None]:
    if quote.amount is not None:
        return quote.amount, quote.amount
    return quote.amount_min, quote.amount_max


def _nightly_from_total(total: PriceQuote, *, nights: int) -> PriceQuote:
    amount = total.amount / nights if total.amount is not None else None
    minimum = total.amount_min / nights if total.amount_min is not None else None
    maximum = total.amount_max / nights if total.amount_max is not None else None
    return total.model_copy(
        update={
            "amount": amount,
            "amount_min": minimum,
            "amount_max": maximum,
            "price_unit": "one room per night",
        }
    )


def _hotel_bounds(
    hotels: list[HotelOption], plan: FareEstimatePlan
) -> tuple[Decimal, Decimal]:
    bounds = [_price_bounds(item.total_price) for item in hotels]
    known = [(low, high) for low, high in bounds if low is not None and high is not None]
    if not known:
        return plan.hotel_total_min, plan.hotel_total_max
    return min(item[0] for item in known), max(item[1] for item in known)


def _source_price_type(options: list[TransportOption]) -> Literal["live_quote", "estimate", "unknown"]:
    return (
        "live_quote"
        if any(item.price.price_type == "live_quote" for item in options)
        else "estimate"
        if any(item.price.price_type == "estimate" for item in options)
        else "unknown"
    )


def _hotel_source_price_type(options: list[HotelOption]) -> Literal["live_quote", "estimate", "unknown"]:
    return (
        "live_quote"
        if any(item.total_price.price_type == "live_quote" for item in options)
        else "estimate"
        if any(item.total_price.price_type == "estimate" for item in options)
        else "unknown"
    )
