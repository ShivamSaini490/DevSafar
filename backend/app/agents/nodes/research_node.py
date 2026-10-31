
import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Any

from app.agents.state import TravelState
from app.integrations.base import ProviderBundle, provider_sources


def build_research_node(
    provider_factory: Callable[[datetime], ProviderBundle],
) -> Any:
    async def research_node(state: TravelState) -> dict[str, Any]:
        requirements = state["requirements"]
        fetched_at = state["fetched_at"]
        if requirements is None or fetched_at is None:
            raise ValueError("Research requires validated requirements and fetched_at")
        providers = provider_factory(fetched_at)
        route_legs, transport, hotels, attractions = await asyncio.gather(
            providers.maps.route_legs(requirements),
            providers.transport.options(requirements),
            providers.hotels.options(requirements),
            providers.places.attractions(requirements),
        )
        return {
            "route_options": route_legs,
            "transport_options": transport,
            "hotels": hotels,
            "attractions": attractions,
            "destination_knowledge": [
                "Stub destination knowledge only; RAG is not connected."
            ],
            "provider_sources": provider_sources(
                providers,
                fetched_at,
                attractions=attractions,
            ),
        }

    return research_node
