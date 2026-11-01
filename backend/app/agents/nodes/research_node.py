import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from app.agents.state import TravelState
from app.core.config import Settings
from app.core.logging import current_request_id
from app.integrations.base import ProviderBundle, provider_sources
from app.rag.retriever import DestinationKnowledgeRetriever, RetrievalResult
from app.schemas.common import DataSource
from app.schemas.trip import DestinationTip, canonical_place_name_for_comparison

logger = logging.getLogger(__name__)


def build_research_node(
    provider_factory: Callable[[datetime], ProviderBundle],
    *,
    settings: Settings,
    rag_retriever: DestinationKnowledgeRetriever | None = None,
) -> Any:
    async def research_node(state: TravelState) -> dict[str, Any]:
        requirements = state["requirements"]
        fetched_at = state["fetched_at"]
        if requirements is None or fetched_at is None:
            raise ValueError("Research requires validated requirements and fetched_at")
        providers = provider_factory(fetched_at)
        route_legs, transport, hotels, attractions, rag_results = await asyncio.gather(
            providers.maps.route_legs(requirements),
            providers.transport.options(requirements),
            providers.hotels.options(requirements),
            providers.places.attractions(requirements),
            _retrieve_destination_knowledge(
                settings=settings,
                retriever=rag_retriever,
                origin=requirements.origin,
                destinations=requirements.destinations,
            ),
        )
        provider_warnings = list(getattr(providers.places, "degradation_warnings", ()))
        sources = provider_sources(
            providers,
            fetched_at,
            attractions=attractions,
        )
        destination_tips: list[DestinationTip] = []
        rag_queries = 0
        if settings.rag_enabled:
            rag_queries = len(rag_results)
            rag_degraded = rag_retriever is None
            updated_dates = []
            for result in rag_results:
                rag_degraded = rag_degraded or result.degraded or not result.items
                for item in result.items[: settings.rag_top_k]:
                    tip = item.to_tip()
                    destination_tips.append(tip)
                    updated_dates.append(tip.updated_at)
            sources.append(
                DataSource(
                    name="rag",
                    price_type="unknown",
                    fetched_at=fetched_at,
                    updated_at=max(updated_dates) if updated_dates else None,
                    status="degraded" if rag_degraded else "ok",
                )
            )
        external_call_counts = dict(state["external_call_counts"])
        external_call_counts["rag_queries"] = rag_queries
        logger.info(
            "Trip external call counts",
            extra={
                "request_id": current_request_id(),
                "rag_queries": rag_queries,
            },
        )
        return {
            "route_options": route_legs,
            "transport_options": transport,
            "hotels": hotels,
            "attractions": attractions,
            "destination_knowledge": destination_tips,
            "external_call_counts": external_call_counts,
            "provider_sources": sources,
            "warnings": list(dict.fromkeys([*state["warnings"], *provider_warnings])),
        }

    return research_node


async def _retrieve_destination_knowledge(
    *,
    settings: Settings,
    retriever: DestinationKnowledgeRetriever | None,
    origin: str | None,
    destinations: list[str],
) -> list[RetrievalResult]:
    if not settings.rag_enabled or retriever is None:
        return []
    canonical_origin = (
        canonical_place_name_for_comparison(origin).casefold() if origin else None
    )
    unique_destinations = list(
        dict.fromkeys(
            canonical
            for destination in destinations
            if (canonical := canonical_place_name_for_comparison(destination))
            and canonical.casefold() != canonical_origin
        )
    )
    return list(
        await asyncio.gather(
            *(retriever.retrieve(destination) for destination in unique_destinations)
        )
    )
