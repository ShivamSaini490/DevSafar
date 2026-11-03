import json
import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from app.core.config import Settings
from app.schemas.common import PriceQuote
from app.schemas.hotel import HotelOption
from app.schemas.transport import RouteLeg, TransportOption
from app.schemas.trip import ModeComparison, TripRequirements
from app.utils.datetime_utils import INDIA_TIME_ZONE

EstimateMode = Literal["road", "train", "bus", "flight"]
HotelTier = Literal["budget", "standard", "comfort"]
ESTIMATE_NOTE = (
    "rough formula estimate, not a fare quote; rates are configurable estimates"
)
UNKNOWN_FLIGHT_NOTE = (
    "nearest airport must be checked; rates are configurable estimates"
)
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
MONEY_QUANTUM = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class FareEstimatePlan:
    route_legs: list[RouteLeg]
    transport_options: list[TransportOption]
    hotels: list[HotelOption]
    mode_comparison: list[ModeComparison]
    recommended_mode: EstimateMode | None
    hotel_total_min: Decimal
    hotel_total_max: Decimal
    food_total_min: Decimal
    food_total_max: Decimal
    local_transport_total_min: Decimal
    local_transport_total_max: Decimal
    warnings: list[str]


@dataclass(frozen=True, slots=True)
class _HotelStay:
    destination: str
    check_in: date
    check_out: date


@dataclass(frozen=True, slots=True)
class _AirportInfo:
    code: str
    latitude: Decimal | None
    longitude: Decimal | None


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _minutes(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_CEILING))


@lru_cache(maxsize=1)
def _airport_aliases() -> dict[str, _AirportInfo]:
    payload = json.loads((DATA_DIR / "city_airports.json").read_text(encoding="utf-8"))
    aliases: dict[str, _AirportInfo] = {}
    for airport in payload:
        info = _AirportInfo(
            code=str(airport["iata_code"]),
            latitude=(
                Decimal(str(airport["latitude"]))
                if airport.get("latitude") is not None
                else None
            ),
            longitude=(
                Decimal(str(airport["longitude"]))
                if airport.get("longitude") is not None
                else None
            ),
        )
        for city in airport["nearest_airport_for"]:
            aliases[str(city).strip().casefold()] = info
    return aliases


@lru_cache(maxsize=1)
def _station_aliases() -> frozenset[str]:
    payload = json.loads((DATA_DIR / "city_stations.json").read_text(encoding="utf-8"))
    return frozenset(
        str(city).strip().casefold()
        for station in payload
        for city in station["station_available_for"]
    )


class FareEstimator:
    """Build deterministic, configurable ranges without external calls."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def airport_code(city: str) -> str | None:
        airport = _airport_aliases().get(city.strip().casefold())
        return airport.code if airport is not None else None

    def build(
        self,
        *,
        requirements: TripRequirements,
        road_legs: list[RouteLeg],
        fetched_at: datetime,
    ) -> FareEstimatePlan:
        options_by_mode: dict[EstimateMode, list[TransportOption]] = {
            "road": [],
            "train": [],
            "bus": [],
            "flight": [],
        }
        for leg in road_legs:
            for mode in options_by_mode:
                options_by_mode[mode].append(
                    self._estimate_leg(mode=mode, leg=leg, fetched_at=fetched_at)
                )

        stays = self._hotel_stays(requirements, road_legs)
        hotels = self._hotel_options(stays, fetched_at=fetched_at)
        hotel_total_min, hotel_total_max = self._hotel_cost_range(stays)
        trip_days = self._trip_days(requirements)
        travelers = Decimal(requirements.travelers)
        food_total_min = _money(
            self.settings.estimate_food_min_per_day_per_traveler
            * Decimal(trip_days)
            * travelers
        )
        food_total_max = _money(
            self.settings.estimate_food_max_per_day_per_traveler
            * Decimal(trip_days)
            * travelers
        )
        local_total_min = _money(
            self.settings.estimate_local_transport_min_per_day_per_traveler
            * Decimal(trip_days)
            * travelers
        )
        local_total_max = _money(
            self.settings.estimate_local_transport_max_per_day_per_traveler
            * Decimal(trip_days)
            * travelers
        )

        comparisons = [
            self._comparison(
                mode=mode,
                options=options_by_mode[mode],
                requirements=requirements,
                fetched_at=fetched_at,
                hotel_total_min=hotel_total_min,
                hotel_total_max=hotel_total_max,
                food_total_min=food_total_min,
                food_total_max=food_total_max,
                local_total_min=local_total_min,
                local_total_max=local_total_max,
            )
            for mode in options_by_mode
        ]
        recommended_mode, recommendation_note = self._recommend(comparisons, requirements)
        if recommended_mode == "road":
            stays = self._hotel_stays(requirements, road_legs, use_actual_road=True)
            hotels = self._hotel_options(stays, fetched_at=fetched_at)
            hotel_total_min, hotel_total_max = self._hotel_cost_range(stays)
            comparisons = [
                self._comparison(
                    mode=mode,
                    options=options_by_mode[mode],
                    requirements=requirements,
                    fetched_at=fetched_at,
                    hotel_total_min=hotel_total_min,
                    hotel_total_max=hotel_total_max,
                    food_total_min=food_total_min,
                    food_total_max=food_total_max,
                    local_total_min=local_total_min,
                    local_total_max=local_total_max,
                )
                for mode in options_by_mode
            ]
            recommended_mode, recommendation_note = self._recommend(
                comparisons,
                requirements,
            )
        comparisons = [
            comparison.model_copy(
                update={
                    "recommended": (
                        comparison.mode == recommended_mode
                        if recommended_mode is not None
                        else None
                    ),
                    "notes": list(
                        dict.fromkeys(
                            [
                                *comparison.notes,
                                *(
                                    [recommendation_note]
                                    if comparison.mode == recommended_mode
                                    or recommended_mode is None
                                    else []
                                ),
                            ]
                        )
                    ),
                }
            )
            for comparison in comparisons
        ]
        route_legs = self._recommended_legs(
            recommended_mode,
            requirements=requirements,
            road_legs=road_legs,
            options_by_mode=options_by_mode,
        )
        warnings = [
            "Rates are configurable estimates; verify fares, schedules, and availability."
        ]
        if recommended_mode is not None and recommended_mode != "road":
            warnings.append("Feasibility based on rough estimates; verify timetables.")
        if recommended_mode is None:
            warnings.append(recommendation_note)
        return FareEstimatePlan(
            route_legs=route_legs,
            transport_options=[
                option for mode in options_by_mode.values() for option in mode
            ],
            hotels=hotels,
            mode_comparison=comparisons,
            recommended_mode=recommended_mode,
            hotel_total_min=hotel_total_min,
            hotel_total_max=hotel_total_max,
            food_total_min=food_total_min,
            food_total_max=food_total_max,
            local_transport_total_min=local_total_min,
            local_transport_total_max=local_total_max,
            warnings=warnings,
        )

    def _estimate_leg(
        self,
        *,
        mode: EstimateMode,
        leg: RouteLeg,
        fetched_at: datetime,
    ) -> TransportOption:
        if mode == "flight":
            return self._flight_leg(leg, fetched_at=fetched_at)
        distance = leg.distance_km
        if distance is None:
            return self._unknown_option(
                mode=mode,
                leg=leg,
                fetched_at=fetched_at,
                note=(
                    "road distance is unavailable; rates are configurable estimates"
                ),
            )
        if mode == "road":
            duration = self._road_duration(leg, distance)
            price_min = price_max = _money(distance * self.settings.fuel_cost_per_km)
            note = ESTIMATE_NOTE
        elif mode == "train":
            duration = self._duration_range(
                distance,
                speed_min=self.settings.estimate_train_speed_min_kmph,
                speed_max=self.settings.estimate_train_speed_max_kmph,
                overhead_min=self.settings.estimate_train_overhead_min_hours,
                overhead_max=self.settings.estimate_train_overhead_max_hours,
            )
            train_rates = (
                self.settings.estimate_train_sleeper_inr_per_km,
                self.settings.estimate_train_3ac_inr_per_km,
                self.settings.estimate_train_2ac_inr_per_km,
            )
            price_min = _money(distance * min(train_rates))
            price_max = _money(distance * max(train_rates))
            station_known = (
                leg.origin.casefold() in _station_aliases()
                and leg.destination.casefold() in _station_aliases()
            )
            checks = (
                distance < self.settings.estimate_train_distance_threshold_km
                or not station_known
            )
            note = (
                f"{ESTIMATE_NOTE}; check station availability"
                if checks
                else ESTIMATE_NOTE
            )
        else:
            duration = self._duration_range(
                distance,
                speed_min=self.settings.estimate_bus_speed_min_kmph,
                speed_max=self.settings.estimate_bus_speed_max_kmph,
                overhead_min=self.settings.estimate_bus_overhead_min_hours,
                overhead_max=self.settings.estimate_bus_overhead_max_hours,
            )
            bus_rates = (
                self.settings.estimate_bus_ordinary_inr_per_km,
                self.settings.estimate_bus_ac_inr_per_km,
                self.settings.estimate_bus_sleeper_inr_per_km,
            )
            price_min = _money(distance * min(bus_rates))
            price_max = _money(distance * max(bus_rates))
            note = ESTIMATE_NOTE
        return TransportOption(
            origin=leg.origin,
            destination=leg.destination,
            mode=mode,
            provider="distance_formula",
            duration_minutes_min=duration[0],
            duration_minutes_max=duration[1],
            distance_km=distance,
            price=PriceQuote(
                amount_min=price_min,
                amount_max=price_max,
                price_type="estimate",
                source="distance_formula",
                fetched_at=fetched_at,
                status="formula_estimate",
                provider="distance_formula",
                observed_at=fetched_at,
                price_unit=(
                    "private vehicle one-way"
                    if mode == "road"
                    else "one traveller one-way"
                ),
                note=note,
            ),
            availability="unknown",
            note=note,
        )

    def _flight_leg(self, leg: RouteLeg, *, fetched_at: datetime) -> TransportOption:
        airports = _airport_aliases()
        origin_airport = airports.get(leg.origin.casefold())
        destination_airport = airports.get(leg.destination.casefold())
        distance = leg.great_circle_distance_km
        if (
            distance is None
            and origin_airport is not None
            and destination_airport is not None
            and origin_airport.latitude is not None
            and origin_airport.longitude is not None
            and destination_airport.latitude is not None
            and destination_airport.longitude is not None
        ):
            distance = self._airport_distance(origin_airport, destination_airport)
        if (
            origin_airport is None
            or destination_airport is None
            or origin_airport.code == destination_airport.code
            or distance is None
        ):
            return self._unknown_option(
                mode="flight",
                leg=leg,
                fetched_at=fetched_at,
                note=UNKNOWN_FLIGHT_NOTE,
                distance=distance,
            )
        duration = self._duration_range(
            distance,
            speed_min=self.settings.estimate_flight_speed_min_kmph,
            speed_max=self.settings.estimate_flight_speed_max_kmph,
            overhead_min=self.settings.estimate_flight_overhead_min_hours,
            overhead_max=self.settings.estimate_flight_overhead_max_hours,
        )
        price_min = max(
            self.settings.estimate_flight_min_fare_min_inr,
            self.settings.estimate_flight_base_min_inr
            + distance * self.settings.estimate_flight_per_km_min_inr,
        )
        price_max = max(
            self.settings.estimate_flight_min_fare_max_inr,
            self.settings.estimate_flight_base_max_inr
            + distance * self.settings.estimate_flight_per_km_max_inr,
        )
        note = (
            f"{ESTIMATE_NOTE}; mapped airports "
            f"{origin_airport.code}-{destination_airport.code}"
        )
        return TransportOption(
            origin=leg.origin,
            destination=leg.destination,
            mode="flight",
            provider="distance_formula",
            duration_minutes_min=duration[0],
            duration_minutes_max=duration[1],
            distance_km=distance,
            price=PriceQuote(
                amount_min=_money(price_min),
                amount_max=_money(price_max),
                price_type="estimate",
                source="distance_formula",
                fetched_at=fetched_at,
                status="formula_estimate",
                provider="distance_formula",
                observed_at=fetched_at,
                price_unit="one adult one-way",
                note=note,
            ),
            availability="unknown",
            note=note,
        )

    @staticmethod
    def _unknown_option(
        *,
        mode: EstimateMode,
        leg: RouteLeg,
        fetched_at: datetime,
        note: str,
        distance: Decimal | None = None,
    ) -> TransportOption:
        return TransportOption(
            origin=leg.origin,
            destination=leg.destination,
            mode=mode,
            provider="distance_formula",
            distance_km=distance if distance is not None else leg.distance_km,
            price=PriceQuote(
                amount=None,
                price_type="unknown",
                source="distance_formula",
                fetched_at=fetched_at,
                status="unavailable",
                provider="distance_formula",
                observed_at=fetched_at,
                price_unit=(
                    "one adult one-way" if mode == "flight" else "one traveller one-way"
                ),
                note=note,
            ),
            availability="unknown",
            note=note,
        )

    def _road_duration(self, leg: RouteLeg, distance: Decimal) -> tuple[int, int]:
        if leg.duration_minutes is not None and leg.duration_source == "osrm":
            return leg.duration_minutes, leg.duration_minutes
        return self._duration_range(
            distance,
            speed_min=self.settings.estimate_road_speed_min_kmph,
            speed_max=self.settings.estimate_road_speed_max_kmph,
            overhead_min=Decimal("0"),
            overhead_max=Decimal("0"),
        )

    @staticmethod
    def _airport_distance(origin: _AirportInfo, destination: _AirportInfo) -> Decimal:
        assert origin.latitude is not None and origin.longitude is not None
        assert destination.latitude is not None and destination.longitude is not None
        origin_lat = math.radians(float(origin.latitude))
        destination_lat = math.radians(float(destination.latitude))
        latitude_delta = destination_lat - origin_lat
        longitude_delta = math.radians(float(destination.longitude - origin.longitude))
        haversine = (
            math.sin(latitude_delta / 2) ** 2
            + math.cos(origin_lat)
            * math.cos(destination_lat)
            * math.sin(longitude_delta / 2) ** 2
        )
        central_angle = 2 * math.asin(min(1.0, math.sqrt(haversine)))
        return Decimal(str(6371.0088 * central_angle)).quantize(Decimal("0.001"))

    @staticmethod
    def _duration_range(
        distance: Decimal,
        *,
        speed_min: Decimal,
        speed_max: Decimal,
        overhead_min: Decimal,
        overhead_max: Decimal,
    ) -> tuple[int, int]:
        minimum = _minutes((distance / speed_max + overhead_min) * Decimal("60"))
        maximum = _minutes((distance / speed_min + overhead_max) * Decimal("60"))
        return minimum, max(minimum, maximum)

    def _comparison(
        self,
        *,
        mode: EstimateMode,
        options: list[TransportOption],
        requirements: TripRequirements,
        fetched_at: datetime,
        hotel_total_min: Decimal,
        hotel_total_max: Decimal,
        food_total_min: Decimal,
        food_total_max: Decimal,
        local_total_min: Decimal,
        local_total_max: Decimal,
    ) -> ModeComparison:
        known = bool(options) and all(
            option.duration_minutes_min is not None
            and option.duration_minutes_max is not None
            and option.price.amount_min is not None
            and option.price.amount_max is not None
            for option in options
        )
        notes = list(dict.fromkeys(option.note for option in options if option.note))
        if not known:
            unknown = PriceQuote(
                amount=None,
                price_type="unknown",
                source="distance_formula",
                fetched_at=fetched_at,
                status="unavailable",
                provider="distance_formula",
                observed_at=fetched_at,
                price_unit="trip transport total",
                note=notes[0] if notes else "estimate inputs are unavailable",
            )
            return ModeComparison(
                mode=mode,
                transport_price=unknown,
                total_price=unknown.model_copy(deep=True),
                notes=notes,
            )
        duration_min = sum(option.duration_minutes_min or 0 for option in options)
        duration_max = sum(option.duration_minutes_max or 0 for option in options)
        transport_min = _money(
            sum((option.price.amount_min or Decimal("0") for option in options), Decimal("0"))
        )
        transport_max = _money(
            sum((option.price.amount_max or Decimal("0") for option in options), Decimal("0"))
        )
        if mode != "road":
            transport_min = _money(transport_min * requirements.travelers)
            transport_max = _money(transport_max * requirements.travelers)
        total_min = _money(
            transport_min + hotel_total_min + food_total_min + local_total_min
        )
        total_max = _money(
            transport_max + hotel_total_max + food_total_max + local_total_max
        )
        meets_deadline = self._meets_deadline(
            requirements,
            duration_minutes_max=duration_max,
        )
        return ModeComparison(
            mode=mode,
            duration_minutes_min=duration_min,
            duration_minutes_max=duration_max,
            transport_price=PriceQuote(
                amount_min=transport_min,
                amount_max=transport_max,
                price_type="estimate",
                source="distance_formula",
                fetched_at=fetched_at,
                status="formula_estimate",
                provider="distance_formula",
                observed_at=fetched_at,
                price_unit="trip transport total",
                note=ESTIMATE_NOTE,
            ),
            total_price=PriceQuote(
                amount_min=total_min,
                amount_max=total_max,
                price_type="estimate",
                source="distance_formula",
                fetched_at=fetched_at,
                status="formula_estimate",
                provider="distance_formula",
                observed_at=fetched_at,
                price_unit="trip total",
                note=(
                    "transport plus hotel, food, and local transport; " + ESTIMATE_NOTE
                ),
            ),
            meets_deadline_estimate=meets_deadline,
            recommended=False,
            notes=notes,
        )

    def _meets_deadline(
        self,
        requirements: TripRequirements,
        *,
        duration_minutes_max: int,
    ) -> bool | None:
        if requirements.start_date is None or requirements.return_deadline is None:
            return None
        non_origin_arrivals = sum(
            1
            for destination in requirements.destinations
            if requirements.origin is None
            or destination.casefold() != requirements.origin.casefold()
        )
        estimated_arrival = datetime.combine(
            requirements.start_date,
            time(hour=6),
            tzinfo=INDIA_TIME_ZONE,
        ) + timedelta(
            minutes=duration_minutes_max,
            hours=self.settings.min_stay_hours_per_destination * non_origin_arrivals,
        )
        return estimated_arrival <= requirements.return_deadline

    @staticmethod
    def _recommend(
        comparisons: list[ModeComparison],
        requirements: TripRequirements,
    ) -> tuple[EstimateMode | None, str]:
        known = [
            comparison
            for comparison in comparisons
            if comparison.transport_price.amount_min is not None
            and comparison.duration_minutes_max is not None
        ]
        if not known:
            return None, "No mode has enough distance data for a recommendation."
        meeting = [
            comparison
            for comparison in known
            if comparison.meets_deadline_estimate is True
        ]
        if meeting:
            selected = min(
                meeting,
                key=lambda item: (
                    item.transport_price.amount_min or Decimal("Infinity"),
                    item.duration_minutes_max or 0,
                ),
            )
            return selected.mode, "Cheapest estimated mode that meets the return deadline."
        selected = min(
            known,
            key=lambda item: (
                item.duration_minutes_max or 0,
                item.transport_price.amount_min or Decimal("Infinity"),
            ),
        )
        if requirements.return_deadline is None:
            return selected.mode, "Fastest estimated mode; no return deadline was provided."
        return selected.mode, "No estimated mode meets the deadline; fastest estimate selected."

    def _recommended_legs(
        self,
        recommended_mode: EstimateMode | None,
        *,
        requirements: TripRequirements,
        road_legs: list[RouteLeg],
        options_by_mode: dict[EstimateMode, list[TransportOption]],
    ) -> list[RouteLeg]:
        if recommended_mode is None:
            return road_legs
        selected_options = options_by_mode[recommended_mode]
        if recommended_mode == "road":
            return [
                leg.model_copy(
                    update={
                        "duration_minutes_min": option.duration_minutes_min,
                        "duration_minutes_max": option.duration_minutes_max,
                        "price": option.price.model_copy(deep=True),
                    }
                )
                for leg, option in zip(road_legs, selected_options, strict=True)
            ]
        departure = (
            datetime.combine(
                requirements.start_date,
                time(hour=6),
                tzinfo=INDIA_TIME_ZONE,
            )
            if requirements.start_date is not None
            else None
        )
        legs: list[RouteLeg] = []
        for source, option in zip(road_legs, selected_options, strict=True):
            duration = option.duration_minutes_max
            arrival = (
                departure + timedelta(minutes=duration)
                if departure is not None and duration is not None
                else None
            )
            legs.append(
                RouteLeg(
                    origin=option.origin,
                    destination=option.destination,
                    mode=recommended_mode,
                    duration_minutes=duration,
                    duration_minutes_min=option.duration_minutes_min,
                    duration_minutes_max=option.duration_minutes_max,
                    duration_source="distance_formula",
                    distance_km=option.distance_km,
                    great_circle_distance_km=source.great_circle_distance_km,
                    departure_at=departure,
                    arrival_at=arrival,
                    price=option.price.model_copy(deep=True),
                )
            )
            if arrival is not None:
                stay_hours = (
                    0
                    if requirements.origin is not None
                    and option.destination.casefold() == requirements.origin.casefold()
                    else self.settings.min_stay_hours_per_destination
                )
                departure = arrival + timedelta(hours=stay_hours)
        return legs

    def _hotel_stays(
        self,
        requirements: TripRequirements,
        road_legs: list[RouteLeg],
        *,
        use_actual_road: bool = False,
    ) -> list[_HotelStay]:
        if requirements.start_date is None or requirements.end_date is None:
            return []
        if use_actual_road:
            actual_stays: list[_HotelStay] = []
            for leg in road_legs:
                for current_segment, next_segment in zip(
                    leg.driving_segments,
                    leg.driving_segments[1:],
                    strict=False,
                ):
                    if next_segment.starts_at.date() > current_segment.ends_at.date():
                        actual_stays.append(
                            _HotelStay(
                                destination="en route",
                                check_in=current_segment.ends_at.date(),
                                check_out=next_segment.starts_at.date(),
                            )
                        )
            for index, leg in enumerate(road_legs):
                if leg.arrival_at is None or (
                    requirements.origin is not None
                    and leg.destination.casefold() == requirements.origin.casefold()
                ):
                    continue
                next_departure = next(
                    (
                        candidate.departure_at
                        for candidate in road_legs[index + 1 :]
                        if candidate.origin.casefold() == leg.destination.casefold()
                        and candidate.departure_at is not None
                    ),
                    None,
                )
                check_out = (
                    next_departure.date()
                    if next_departure is not None
                    else requirements.end_date
                )
                if check_out > leg.arrival_at.date():
                    actual_stays.append(
                        _HotelStay(
                            destination=leg.destination,
                            check_in=leg.arrival_at.date(),
                            check_out=check_out,
                        )
                    )
            return actual_stays
        leg_dates = self.approximate_leg_dates(requirements, len(road_legs))
        stays: list[_HotelStay] = []
        for index, leg in enumerate(road_legs):
            if (
                requirements.origin is not None
                and leg.destination.casefold() == requirements.origin.casefold()
            ):
                continue
            check_in = leg_dates[index]
            check_out = next(
                (
                    leg_dates[next_index]
                    for next_index, candidate in enumerate(road_legs[index + 1 :], index + 1)
                    if candidate.origin.casefold() == leg.destination.casefold()
                ),
                requirements.end_date,
            )
            if check_out > check_in:
                stays.append(
                    _HotelStay(
                        destination=leg.destination,
                        check_in=check_in,
                        check_out=check_out,
                    )
                )
        return stays

    def _hotel_options(
        self,
        stays: list[_HotelStay],
        *,
        fetched_at: datetime,
    ) -> list[HotelOption]:
        tiers: tuple[tuple[HotelTier, Decimal, Decimal], ...] = (
            (
                "budget",
                self.settings.estimate_hotel_budget_min_inr,
                self.settings.estimate_hotel_budget_max_inr,
            ),
            (
                "standard",
                self.settings.estimate_hotel_standard_min_inr,
                self.settings.estimate_hotel_standard_max_inr,
            ),
            (
                "comfort",
                self.settings.estimate_hotel_comfort_min_inr,
                self.settings.estimate_hotel_comfort_max_inr,
            ),
        )
        options: list[HotelOption] = []
        for stay in stays:
            nights = Decimal((stay.check_out - stay.check_in).days)
            for tier, minimum, maximum in tiers:
                options.append(
                    HotelOption(
                        destination=stay.destination,
                        name=(
                            f"{tier.title()} tier estimate in {stay.destination} "
                            "(no availability claim)"
                        ),
                        check_in=stay.check_in,
                        check_out=stay.check_out,
                        nightly_price=PriceQuote(
                            amount_min=_money(minimum),
                            amount_max=_money(maximum),
                            price_type="estimate",
                            source="tier_assumption",
                            fetched_at=fetched_at,
                            status="formula_estimate",
                            provider="tier_assumption",
                            observed_at=fetched_at,
                            price_unit="one room per night",
                            note=ESTIMATE_NOTE,
                        ),
                        total_price=PriceQuote(
                            amount_min=_money(minimum * nights),
                            amount_max=_money(maximum * nights),
                            price_type="estimate",
                            source="tier_assumption",
                            fetched_at=fetched_at,
                            status="formula_estimate",
                            provider="tier_assumption",
                            observed_at=fetched_at,
                            price_unit="one room, full stay",
                            note=ESTIMATE_NOTE,
                        ),
                        availability="unknown",
                        tier=tier,
                    )
                )
        return options

    def _hotel_cost_range(self, stays: list[_HotelStay]) -> tuple[Decimal, Decimal]:
        nights = sum(
            (Decimal((stay.check_out - stay.check_in).days) for stay in stays),
            Decimal("0"),
        )
        return (
            _money(nights * self.settings.estimate_hotel_budget_min_inr),
            _money(nights * self.settings.estimate_hotel_comfort_max_inr),
        )

    @staticmethod
    def approximate_leg_dates(
        requirements: TripRequirements,
        leg_count: int,
    ) -> list[date]:
        if requirements.start_date is None or requirements.end_date is None:
            return []
        if leg_count <= 1:
            return [requirements.start_date] * leg_count
        span_days = max(0, (requirements.end_date - requirements.start_date).days)
        return [
            requirements.start_date
            + timedelta(days=(index * span_days) // (leg_count - 1))
            for index in range(leg_count)
        ]

    @staticmethod
    def _trip_days(requirements: TripRequirements) -> int:
        if requirements.start_date is None or requirements.end_date is None:
            return 0
        return (requirements.end_date - requirements.start_date).days + 1
