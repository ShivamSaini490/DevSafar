from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict

from app.core.config import Settings
from app.core.security import utc_now
from app.integrations.base import ProviderFailure, SafeProviderHttpClient
from app.schemas.transport import FlightSearchAlternative


class _LooseModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _SearchMetadata(_LooseModel):
    status: str | None = None


class _SearchParameters(_LooseModel):
    currency: str | None = None


class _Airport(_LooseModel):
    time: str | None = None


class _Segment(_LooseModel):
    departure_airport: _Airport | None = None
    arrival_airport: _Airport | None = None
    airline: str | None = None


class _FlightCandidate(_LooseModel):
    flights: list[_Segment] = []
    total_duration: int | None = None
    price: int | float | Decimal | str | None = None


class _FlightsResponse(_LooseModel):
    search_metadata: _SearchMetadata | None = None
    search_parameters: _SearchParameters | None = None
    best_flights: list[_FlightCandidate] | None = None
    other_flights: list[_FlightCandidate] | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class FlightProviderResult:
    amount: Decimal | None
    observed_at: datetime
    total_duration_minutes: int | None = None
    alternatives: tuple[FlightSearchAlternative, ...] = ()

    @property
    def empty(self) -> bool:
        return self.amount is None


class SerpApiFlightsProvider:
    name = "SerpApi Google Flights"

    def __init__(self, settings: Settings, http: SafeProviderHttpClient) -> None:
        self.settings = settings
        self.http = http

    async def search_one_way(
        self,
        *,
        departure_id: str,
        arrival_id: str,
        outbound_date: date,
        adults: int = 1,
    ) -> FlightProviderResult:
        if not self.settings.serpapi_configured:
            raise ProviderFailure("request_error", "SerpApi is disabled or missing a key")
        assert self.settings.google_serp_api_key is not None
        key = self.settings.google_serp_api_key.get_secret_value()
        response = await self.http.get_json(
            provider=self.name,
            url=self.settings.serpapi_base_url,
            params={
                "engine": "google_flights",
                "departure_id": departure_id,
                "arrival_id": arrival_id,
                "outbound_date": outbound_date.isoformat(),
                "type": 2,
                "currency": "INR",
                "adults": adults,
                "api_key": key,
                "output": "json",
            },
            response_model=_FlightsResponse,
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

        raw_candidates = [
            *(response.best_flights or []),
            *(response.other_flights or []),
        ]
        candidates: list[tuple[Decimal, _FlightCandidate]] = []
        for candidate in raw_candidates:
            amount = _positive_decimal(candidate.price)
            if amount is not None:
                candidates.append((amount, candidate))
        if raw_candidates and not candidates:
            raise ProviderFailure("schema_mismatch", f"{self.name} returned no valid fare")
        observed_at = utc_now()
        if not candidates:
            return FlightProviderResult(amount=None, observed_at=observed_at)

        candidates.sort(key=lambda item: item[0])
        cheapest_amount, cheapest = candidates[0]
        alternatives = tuple(
            _alternative(amount, candidate) for amount, candidate in candidates[:4]
        )
        return FlightProviderResult(
            amount=cheapest_amount,
            observed_at=observed_at,
            total_duration_minutes=cheapest.total_duration,
            alternatives=alternatives,
        )


def _positive_decimal(value: object) -> Decimal | None:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return amount.quantize(Decimal("0.01")) if amount > 0 and amount.is_finite() else None


def _alternative(amount: Decimal, candidate: _FlightCandidate) -> FlightSearchAlternative:
    airlines = list(
        dict.fromkeys(segment.airline for segment in candidate.flights if segment.airline)
    )
    departure = (
        candidate.flights[0].departure_airport.time
        if candidate.flights and candidate.flights[0].departure_airport
        else None
    )
    arrival = (
        candidate.flights[-1].arrival_airport.time
        if candidate.flights and candidate.flights[-1].arrival_airport
        else None
    )
    return FlightSearchAlternative(
        airline=" / ".join(airlines) or None,
        amount=amount,
        total_duration_minutes=candidate.total_duration,
        stops=max(0, len(candidate.flights) - 1),
        departure_time=departure,
        arrival_time=arrival,
    )
