from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.core.config import Settings
from app.core.security import utc_now
from app.integrations.base import ProviderFailure, SafeProviderHttpClient


class _LooseModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _SearchMetadata(_LooseModel):
    status: str | None = None


class _SearchParameters(_LooseModel):
    currency: str | None = None


class _Rate(_LooseModel):
    extracted_after_taxes_fees: int | float | Decimal | str | None = None
    extracted_display_price: int | float | Decimal | str | None = None
    extracted_lowest: int | float | Decimal | str | None = None


class _Property(_LooseModel):
    name: str | None = None
    rate_per_night: _Rate | None = None
    total_rate: _Rate | None = None


class _HotelsResponse(_LooseModel):
    search_metadata: _SearchMetadata | None = None
    search_parameters: _SearchParameters | None = None
    properties: list[_Property] | None = None
    error: str | None = None


HotelTier = Literal["budget", "standard", "comfort"]


@dataclass(frozen=True, slots=True)
class HotelProviderOption:
    name: str
    total_amount: Decimal
    nightly_amount: Decimal
    tier: HotelTier | None
    includes_taxes_fees: bool


@dataclass(frozen=True, slots=True)
class HotelProviderResult:
    options: tuple[HotelProviderOption, ...]
    observed_at: datetime

    @property
    def empty(self) -> bool:
        return not self.options


class SerpApiHotelsProvider:
    name = "SerpApi Google Hotels"

    def __init__(self, settings: Settings, http: SafeProviderHttpClient) -> None:
        self.settings = settings
        self.http = http

    async def search(
        self,
        *,
        city: str,
        check_in: date,
        check_out: date,
        adults: int,
    ) -> HotelProviderResult:
        if not self.settings.serpapi_configured:
            raise ProviderFailure("request_error", "SerpApi is disabled or missing a key")
        assert self.settings.google_serp_api_key is not None
        key = self.settings.google_serp_api_key.get_secret_value()
        response = await self.http.get_json(
            provider=self.name,
            url=self.settings.serpapi_base_url,
            params={
                "engine": "google_hotels",
                "q": f"Hotels in {city}",
                "check_in_date": check_in.isoformat(),
                "check_out_date": check_out.isoformat(),
                "adults": adults,
                "currency": "INR",
                "gl": "in",
                "api_key": key,
                "output": "json",
            },
            response_model=_HotelsResponse,
            secret_values=(key,),
        )
        status = (response.search_metadata.status if response.search_metadata else None) or ""
        if status.casefold() == "error":
            raise ProviderFailure("server_error", f"{self.name} search failed")
        if response.error and status.casefold() != "success":
            raise ProviderFailure("request_error", f"{self.name} search failed")
        currency = response.search_parameters.currency if response.search_parameters else None
        if currency is not None and currency.upper() != "INR":
            raise ProviderFailure("schema_mismatch", f"{self.name} returned non-INR prices")
        nights = max(1, (check_out - check_in).days)
        parsed: list[tuple[str, Decimal, Decimal, bool]] = []
        for index, property_result in enumerate(response.properties or []):
            total, includes_taxes = _preferred_rate(property_result.total_rate)
            nightly, _nightly_includes_taxes = _preferred_rate(property_result.rate_per_night)
            if total is None:
                continue
            if nightly is None:
                nightly = (total / Decimal(nights)).quantize(Decimal("0.01"))
            parsed.append(
                (
                    property_result.name or f"Search result property {index + 1}",
                    total,
                    nightly,
                    includes_taxes,
                )
            )
        if response.properties and not parsed:
            raise ProviderFailure("schema_mismatch", f"{self.name} returned no valid hotel rate")
        parsed.sort(key=lambda item: item[1])
        selected = _select_tiers(parsed)
        return HotelProviderResult(options=tuple(selected), observed_at=utc_now())


def _preferred_rate(rate: _Rate | None) -> tuple[Decimal | None, bool]:
    if rate is None:
        return None, False
    after_tax = _positive_decimal(rate.extracted_after_taxes_fees)
    if after_tax is not None:
        return after_tax, True
    available = _positive_decimal(rate.extracted_display_price)
    if available is None:
        available = _positive_decimal(rate.extracted_lowest)
    return available, False


def _positive_decimal(value: object) -> Decimal | None:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return amount.quantize(Decimal("0.01")) if amount > 0 and amount.is_finite() else None


def _select_tiers(
    rows: list[tuple[str, Decimal, Decimal, bool]],
) -> list[HotelProviderOption]:
    if not rows:
        return []
    tier_indexes: list[tuple[HotelTier, int]]
    if len(rows) >= 5:
        tier_indexes = [
            ("budget", round((len(rows) - 1) * 0.20)),
            ("standard", round((len(rows) - 1) * 0.50)),
            ("comfort", round((len(rows) - 1) * 0.80)),
        ]
    elif len(rows) == 1:
        tier_indexes = [("budget", 0)]
    elif len(rows) == 2:
        tier_indexes = [("budget", 0), ("comfort", 1)]
    else:
        tier_indexes = [("budget", 0), ("standard", len(rows) // 2), ("comfort", len(rows) - 1)]
    return [
        HotelProviderOption(
            name=rows[index][0],
            total_amount=rows[index][1],
            nightly_amount=rows[index][2],
            tier=tier,
            includes_taxes_fees=rows[index][3],
        )
        for tier, index in tier_indexes
    ]
