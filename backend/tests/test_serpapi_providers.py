import logging
from datetime import date, datetime

import httpx
import pytest

from app.core.config import Settings
from app.core.logging import configure_logging
from app.integrations.base import ProviderFailure, SafeProviderHttpClient
from app.integrations.serpapi_flights import SerpApiFlightsProvider
from app.integrations.serpapi_hotels import SerpApiHotelsProvider
from app.utils.datetime_utils import INDIA_TIME_ZONE


def _settings(**updates: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "secret_key": "test-secret",
        "serpapi_enabled": True,
        "google_serp_api_key": "fake-serp-key",
    }
    values.update(updates)
    return Settings(_env_file=None, **values)


def _safe_client(
    client: httpx.AsyncClient,
    *,
    sleep: object | None = None,
) -> SafeProviderHttpClient:
    kwargs = {}
    if sleep is not None:
        kwargs["sleep"] = sleep
    return SafeProviderHttpClient(
        client,
        timeout_seconds=1,
        max_retries=2,
        max_retry_wait_seconds=0.25,
        auth_circuit_minutes=10,
        now_provider=lambda: datetime(2026, 11, 3, tzinfo=INDIA_TIME_ZONE),
        jitter=lambda: 0,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_flights_combines_lists_and_keeps_cheapest_with_display_alternatives() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["engine"] == "google_flights"
        assert request.url.params["type"] == "2"
        assert request.url.params["currency"] == "INR"
        assert request.url.params["adults"] == "1"
        return httpx.Response(
            200,
            json={
                "search_metadata": {"status": "Success"},
                "search_parameters": {"currency": "INR"},
                "best_flights": [
                    {
                        "price": 6200,
                        "total_duration": 130,
                        "flights": [
                            {
                                "airline": "Example Air",
                                "departure_airport": {"time": "2026-11-03 08:00"},
                                "arrival_airport": {"time": "2026-11-03 10:10"},
                            }
                        ],
                    }
                ],
                "other_flights": [
                    {
                        "price": 5100,
                        "total_duration": 145,
                        "flights": [
                            {
                                "airline": "Low Fare Air",
                                "departure_airport": {"time": "2026-11-03 09:00"},
                                "arrival_airport": {"time": "2026-11-03 11:25"},
                            }
                        ],
                    }
                ],
            },
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await SerpApiFlightsProvider(
            _settings(), _safe_client(client)
        ).search_one_way(
            departure_id="HYD",
            arrival_id="DEL",
            outbound_date=date(2026, 11, 3),
        )

    assert result.amount == 5100
    assert result.total_duration_minutes == 145
    assert result.alternatives[0].airline == "Low Fare Air"
    assert result.alternatives[0].departure_time == "2026-11-03 09:00"


@pytest.mark.asyncio
async def test_successful_empty_flight_result_is_not_a_provider_failure() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "search_metadata": {"status": "Success"},
                "search_parameters": {"currency": "INR"},
                "best_flights": [],
                "other_flights": [],
            },
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await SerpApiFlightsProvider(
            _settings(), _safe_client(client)
        ).search_one_way(
            departure_id="HYD",
            arrival_id="DEL",
            outbound_date=date(2026, 11, 3),
        )
    assert result.empty is True


@pytest.mark.asyncio
async def test_hotels_prefer_full_stay_after_tax_totals_and_build_percentile_tiers() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["q"] == "Hotels in Delhi"
        assert request.url.params["gl"] == "in"
        properties = []
        for index, amount in enumerate((2000, 3000, 4000, 5000, 6000), start=1):
            properties.append(
                {
                    "name": f"Hotel {index}",
                    "total_rate": {
                        "extracted_display_price": amount - 200,
                        "extracted_after_taxes_fees": amount,
                    },
                    "rate_per_night": {
                        "extracted_after_taxes_fees": amount / 2,
                    },
                }
            )
        return httpx.Response(
            200,
            json={
                "search_metadata": {"status": "Success"},
                "search_parameters": {"currency": "INR"},
                "properties": properties,
            },
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await SerpApiHotelsProvider(_settings(), _safe_client(client)).search(
            city="Delhi",
            check_in=date(2026, 11, 3),
            check_out=date(2026, 11, 5),
            adults=2,
        )
    assert [item.tier for item in result.options] == ["budget", "standard", "comfort"]
    assert result.options[0].total_amount == 3000
    assert all(item.includes_taxes_fees for item in result.options)


@pytest.mark.asyncio
async def test_401_is_not_retried_and_opens_auth_circuit() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, json={"error": "bad key"}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        safe = _safe_client(client)
        provider = SerpApiFlightsProvider(_settings(), safe)
        with pytest.raises(ProviderFailure, match="authentication failed"):
            await provider.search_one_way(
                departure_id="HYD",
                arrival_id="DEL",
                outbound_date=date(2026, 11, 3),
            )
        with pytest.raises(ProviderFailure, match="circuit is open"):
            await provider.search_one_way(
                departure_id="HYD",
                arrival_id="DEL",
                outbound_date=date(2026, 11, 3),
            )
    assert calls == 1


@pytest.mark.asyncio
async def test_429_wait_is_bounded_and_not_retried() -> None:
    calls = 0
    waits: list[float] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "60"}, request=request)

    async def fake_sleep(value: float) -> None:
        waits.append(value)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = SerpApiFlightsProvider(_settings(), _safe_client(client, sleep=fake_sleep))
        with pytest.raises(ProviderFailure) as raised:
            await provider.search_one_way(
                departure_id="HYD",
                arrival_id="DEL",
                outbound_date=date(2026, 11, 3),
            )
    assert raised.value.code == "quota"
    assert calls == 1
    assert waits == [0.25]


@pytest.mark.asyncio
async def test_timeout_retries_are_bounded_to_two() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("timed out", request=request)

    async def no_sleep(_value: float) -> None:
        return None

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = SerpApiFlightsProvider(_settings(), _safe_client(client, sleep=no_sleep))
        with pytest.raises(ProviderFailure) as raised:
            await provider.search_one_way(
                departure_id="HYD",
                arrival_id="DEL",
                outbound_date=date(2026, 11, 3),
            )
    assert raised.value.code == "timeout"
    assert calls == 3


@pytest.mark.asyncio
async def test_fake_key_is_redacted_from_logging_and_exception_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_key = "fake-key-that-must-never-appear"
    configure_logging("INFO")

    async def handler(request: httpx.Request) -> httpx.Response:
        logging.getLogger("httpx").warning("provider URL %s", request.url)
        return httpx.Response(401, json={"error": fake_key}, request=request)

    settings = _settings(google_serp_api_key=fake_key)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = SerpApiFlightsProvider(settings, _safe_client(client))
        with caplog.at_level(logging.WARNING), pytest.raises(ProviderFailure) as raised:
            await provider.search_one_way(
                departure_id="HYD",
                arrival_id="DEL",
                outbound_date=date(2026, 11, 3),
            )
    assert fake_key not in caplog.text
    assert fake_key not in str(raised.value)
