# Estimate rates to verify

> **PLACEHOLDER - owner must verify against official sources.** These defaults are
> configurable rough-estimate inputs, not official fares, schedules, availability, or
> booking quotes. Fill the final column only after reviewing an appropriate official
> source. These formulas are the final fallback only, after cache, a configured live
> provider, and comparable price history. Until then, API results remain labelled
> `formula_estimate`; they are never booking quotes.

| Config key | Default | Unit / use | Official source URL |
|---|---:|---|---|
| `FUEL_COST_PER_KM` | 12.00 | INR/km, private road estimate | |
| `ESTIMATE_TRAIN_SLEEPER_INR_PER_KM` | 0.75 | INR/km, sleeper lower bound | |
| `ESTIMATE_TRAIN_3AC_INR_PER_KM` | 1.50 | INR/km, 3AC reference | |
| `ESTIMATE_TRAIN_2AC_INR_PER_KM` | 2.25 | INR/km, 2AC upper bound | |
| `ESTIMATE_BUS_ORDINARY_INR_PER_KM` | 1.20 | INR/km, ordinary bus lower bound | |
| `ESTIMATE_BUS_AC_INR_PER_KM` | 2.00 | INR/km, AC bus reference | |
| `ESTIMATE_BUS_SLEEPER_INR_PER_KM` | 2.50 | INR/km, sleeper bus upper bound | |
| `ESTIMATE_FLIGHT_BASE_MIN_INR` | 2500 | INR, base lower bound | |
| `ESTIMATE_FLIGHT_BASE_MAX_INR` | 4500 | INR, base upper bound | |
| `ESTIMATE_FLIGHT_PER_KM_MIN_INR` | 3.00 | INR/km, flight lower bound | |
| `ESTIMATE_FLIGHT_PER_KM_MAX_INR` | 7.00 | INR/km, flight upper bound | |
| `ESTIMATE_FLIGHT_MIN_FARE_MIN_INR` | 3000 | INR, minimum lower bound | |
| `ESTIMATE_FLIGHT_MIN_FARE_MAX_INR` | 5000 | INR, minimum upper bound | |
| `ESTIMATE_ROAD_SPEED_MIN_KMPH` | 40 | km/h, road lower speed | |
| `ESTIMATE_ROAD_SPEED_MAX_KMPH` | 65 | km/h, road upper speed | |
| `ESTIMATE_TRAIN_SPEED_MIN_KMPH` | 45 | km/h, train lower speed | |
| `ESTIMATE_TRAIN_SPEED_MAX_KMPH` | 70 | km/h, train upper speed | |
| `ESTIMATE_BUS_SPEED_MIN_KMPH` | 35 | km/h, bus lower speed | |
| `ESTIMATE_BUS_SPEED_MAX_KMPH` | 55 | km/h, bus upper speed | |
| `ESTIMATE_FLIGHT_SPEED_MIN_KMPH` | 650 | km/h, flight lower speed | |
| `ESTIMATE_FLIGHT_SPEED_MAX_KMPH` | 800 | km/h, flight upper speed | |
| `ESTIMATE_TRAIN_OVERHEAD_MIN_HOURS` | 1 | hours, station overhead lower bound | |
| `ESTIMATE_TRAIN_OVERHEAD_MAX_HOURS` | 2 | hours, station overhead upper bound | |
| `ESTIMATE_BUS_OVERHEAD_MIN_HOURS` | 0.5 | hours, bus overhead lower bound | |
| `ESTIMATE_BUS_OVERHEAD_MAX_HOURS` | 1 | hours, bus overhead upper bound | |
| `ESTIMATE_FLIGHT_OVERHEAD_MIN_HOURS` | 3 | hours, airport overhead lower bound | |
| `ESTIMATE_FLIGHT_OVERHEAD_MAX_HOURS` | 5 | hours, airport overhead upper bound | |
| `ESTIMATE_TRAIN_DISTANCE_THRESHOLD_KM` | 100 | km, station caution threshold | |
| `ESTIMATE_HOTEL_BUDGET_MIN_INR` | 1000 | INR/night, budget lower bound | |
| `ESTIMATE_HOTEL_BUDGET_MAX_INR` | 1800 | INR/night, budget upper bound | |
| `ESTIMATE_HOTEL_STANDARD_MIN_INR` | 2000 | INR/night, standard lower bound | |
| `ESTIMATE_HOTEL_STANDARD_MAX_INR` | 3500 | INR/night, standard upper bound | |
| `ESTIMATE_HOTEL_COMFORT_MIN_INR` | 4000 | INR/night, comfort lower bound | |
| `ESTIMATE_HOTEL_COMFORT_MAX_INR` | 6500 | INR/night, comfort upper bound | |
| `ESTIMATE_FOOD_MIN_PER_DAY_PER_TRAVELER` | 400 | INR/day/traveller, food lower bound | |
| `ESTIMATE_FOOD_MAX_PER_DAY_PER_TRAVELER` | 800 | INR/day/traveller, food upper bound | |
| `ESTIMATE_LOCAL_TRANSPORT_MIN_PER_DAY_PER_TRAVELER` | 250 | INR/day/traveller, local lower bound | |
| `ESTIMATE_LOCAL_TRANSPORT_MAX_PER_DAY_PER_TRAVELER` | 600 | INR/day/traveller, local upper bound | |

The airport and station mapping files are reviewable routing hints only. They do not
prove that a specific service operates, has seats, or is appropriate for the requested
trip. Unknown or missing mappings must stay unknown in the API response.
