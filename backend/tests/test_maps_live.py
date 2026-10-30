import os
from datetime import date

import httpx
import pytest

from app.core.config import Settings
from app.db.session import create_redis_client
from app.integrations.maps_provider import OsmMapsProvider
from app.schemas.trip import TripRequirements


@pytest.mark.live
@pytest.mark.skipif(
    os.getenv("RUN_LIVE_MAPS_TESTS") != "1",
    reason="Set RUN_LIVE_MAPS_TESTS=1 to call Nominatim and public OSRM.",
)
@pytest.mark.asyncio
async def test_live_hyderabad_to_puducherry_road_route(settings: Settings) -> None:
    live_settings = settings.model_copy(update={"maps_provider": "osm"})
    redis = create_redis_client(live_settings)
    async with httpx.AsyncClient() as client:
        provider = OsmMapsProvider(live_settings, redis, client=client)
        legs = await provider.route_legs(
            TripRequirements(
                origin="Hyderabad",
                destinations=["Puducherry"],
                start_date=date(2026, 10, 30),
                end_date=date(2026, 10, 31),
            )
        )
    await redis.aclose()
    assert len(legs) == 1
    assert legs[0].duration_source == "osrm"
    assert legs[0].distance_km is not None
    assert legs[0].duration_minutes is not None
