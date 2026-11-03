import os
from datetime import date, timedelta

import httpx
import pytest

from app.core.config import Settings
from app.integrations.base import SafeProviderHttpClient
from app.integrations.serpapi_flights import SerpApiFlightsProvider
from app.integrations.serpapi_hotels import SerpApiHotelsProvider


@pytest.mark.live
@pytest.mark.skipif(
    os.getenv("RUN_LIVE_SERPAPI_TESTS") != "1",
    reason="Set RUN_LIVE_SERPAPI_TESTS=1 to call SerpApi.",
)
@pytest.mark.asyncio
async def test_opt_in_live_serpapi_flight_and_hotel_smoke() -> None:
    """Spend exactly one flight and one hotel search only when explicitly opted in."""
    api_key = os.getenv("GOOGLE_SERP_API_KEY")
    if os.getenv("RUN_LIVE_SERPAPI_TESTS") != "1" or not api_key:
        pytest.skip(
            "Set RUN_LIVE_SERPAPI_TESTS=1 and export GOOGLE_SERP_API_KEY to run."
        )
    settings = Settings(
        _env_file=None,
        environment="test",
        secret_key="live-smoke-test-only",
        serpapi_enabled=True,
        google_serp_api_key=api_key,
    )
    outbound = date.today() + timedelta(days=14)
    checkout = outbound + timedelta(days=1)
    async with httpx.AsyncClient() as client:
        safe_http = SafeProviderHttpClient(
            client,
            timeout_seconds=settings.serpapi_timeout_seconds,
            max_retries=settings.serpapi_max_retries,
            max_retry_wait_seconds=settings.serpapi_max_retry_wait_seconds,
            auth_circuit_minutes=settings.serpapi_auth_circuit_minutes,
        )
        flight = await SerpApiFlightsProvider(settings, safe_http).search_one_way(
            departure_id="HYD",
            arrival_id="DEL",
            outbound_date=outbound,
        )
        hotels = await SerpApiHotelsProvider(settings, safe_http).search(
            city="Delhi",
            check_in=outbound,
            check_out=checkout,
            adults=1,
        )

    assert flight.amount is None or flight.amount > 0
    assert all(option.total_amount > 0 for option in hotels.options)
