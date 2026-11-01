
import asyncio
import html
import json
import logging
import re
import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime
from time import perf_counter
from typing import Any, Protocol, TypeVar, cast

from pydantic import HttpUrl, TypeAdapter
from redis.asyncio import Redis

from app.core.logging import current_request_id
from app.rag.cache import (
    RAG_QUERY_VECTOR_CACHE_TTL_SECONDS,
    destination_tips_cache_key,
    query_vector_cache_key,
)
from app.rag.embeddings import EmbeddingProvider
from app.rag.vector_store import KnowledgeVectorStore, VectorSearchHit
from app.schemas.trip import DestinationTip, canonical_place_name_for_comparison
from app.utils.url_validator import validate_public_https_url

logger = logging.getLogger(__name__)
RAG_QUERY_INTENT = "evergreen visitor guidance and practical destination context"
_MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[([^]]*)\]\([^)]+\)")
_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^]]+)\]\([^)]+\)")
_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
_RAW_URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
_HTTP_URL = TypeAdapter(HttpUrl)
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RetrievedKnowledge:
    destination: str
    text: str
    title: str
    source_url: str
    updated_at: date
    score: float

    def to_tip(self) -> DestinationTip:
        return DestinationTip(
            title=self.title,
            snippet=plain_text_snippet(self.text, limit=300),
            source_url=_HTTP_URL.validate_python(self.source_url),
            updated_at=self.updated_at,
        )


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    items: list[RetrievedKnowledge]
    degraded: bool


class DestinationKnowledgeRetriever(Protocol):
    async def retrieve(self, destination: str) -> RetrievalResult: ...


class RAGRetriever:
    def __init__(
        self,
        embedder: EmbeddingProvider,
        vector_store: KnowledgeVectorStore,
        *,
        top_k: int,
        score_threshold: float,
        timeout_seconds: float,
        redis: Redis | None = None,
        model_name: str | None = None,
        collection_name: str = "devsafar_travel_knowledge",
        cache_ttl_seconds: int = 3600,
    ) -> None:
        self.embedder = embedder
        self.vector_store = vector_store
        self.top_k = top_k
        self.score_threshold = score_threshold
        self.timeout_seconds = timeout_seconds
        self.redis = redis
        self.model_name = model_name or str(getattr(embedder, "model_name", "unknown"))
        self.collection_name = collection_name
        self.cache_ttl_seconds = cache_ttl_seconds

    async def retrieve(self, destination: str) -> RetrievalResult:
        canonical_destination = canonical_place_name_for_comparison(destination)
        query = f"{canonical_destination}: {RAG_QUERY_INTENT}"
        model_state = str(getattr(self.embedder, "state", "ready"))
        if model_state == "not_ready":
            logger.info(
                "embedding model warming up",
                extra={"request_id": current_request_id()},
            )
            return RetrievalResult(items=[], degraded=True)
        if model_state == "failed":
            logger.warning(
                "RAG embedding model unavailable; continuing without destination knowledge",
                extra={
                    "request_id": current_request_id(),
                    "error_type": str(
                        getattr(self.embedder, "load_error_type", "ModelLoadFailed")
                    ),
                },
            )
            return RetrievalResult(items=[], degraded=True)

        cached_items = await self._read_tips_cache(canonical_destination)
        if cached_items is not None:
            return RetrievalResult(items=cached_items[: self.top_k], degraded=False)

        deadline = asyncio.get_running_loop().time() + self.timeout_seconds
        try:
            vector = await self._read_vector_cache(canonical_destination)
            if vector is None:
                vector = await self._run_stage(
                    "embed",
                    lambda: self.embedder.embed_query(query),
                    deadline=deadline,
                )
                await self._write_vector_cache(canonical_destination, vector)
            hits = await self._run_stage(
                "qdrant_search",
                lambda: self.vector_store.search(
                    destination=canonical_destination,
                    vector=vector,
                    top_k=self.top_k,
                    score_threshold=self.score_threshold,
                ),
                deadline=deadline,
            )
            items = self._validated_items(canonical_destination, hits)
            await self._write_tips_cache(canonical_destination, items[: self.top_k])
            return RetrievalResult(items=items[: self.top_k], degraded=False)
        except TimeoutError:
            return RetrievalResult(items=[], degraded=True)
        except Exception as exc:
            logger.warning(
                "RAG retrieval failed; continuing without destination knowledge",
                extra={
                    "request_id": current_request_id(),
                    "error_type": type(exc).__name__,
                },
            )
            return RetrievalResult(items=[], degraded=True)

    async def _run_stage(
        self,
        stage: str,
        operation: Callable[[], Awaitable[T]],
        *,
        deadline: float,
    ) -> T:
        started_at = perf_counter()
        remaining = deadline - asyncio.get_running_loop().time()
        try:
            if remaining <= 0:
                raise TimeoutError
            async with asyncio.timeout(remaining):
                return await operation()
        except TimeoutError:
            logger.warning(
                "RAG operation timed out",
                extra={
                    "request_id": current_request_id(),
                    "stage": stage,
                    "elapsed_ms": _elapsed_ms(started_at),
                },
            )
            raise

    async def _read_vector_cache(self, destination: str) -> list[float] | None:
        if self.redis is None:
            return None
        key = query_vector_cache_key(
            model_name=self.model_name,
            destination=destination,
        )
        try:
            cached = await self.redis.get(key)
            if cached is None:
                return None
            value = json.loads(cached)
            if not isinstance(value, list) or not value:
                raise ValueError("Invalid cached RAG query vector")
            return [float(item) for item in value]
        except (TypeError, ValueError):
            await self._delete_cache_key(key)
            return None
        except Exception as exc:
            _log_cache_failure("read_query_vector", exc)
            return None

    async def _write_vector_cache(self, destination: str, vector: list[float]) -> None:
        if self.redis is None:
            return
        try:
            await self.redis.set(
                query_vector_cache_key(
                    model_name=self.model_name,
                    destination=destination,
                ),
                json.dumps(vector, separators=(",", ":")),
                ex=RAG_QUERY_VECTOR_CACHE_TTL_SECONDS,
            )
        except Exception as exc:
            _log_cache_failure("write_query_vector", exc)

    async def _read_tips_cache(self, destination: str) -> list[RetrievedKnowledge] | None:
        if self.redis is None:
            return None
        key = destination_tips_cache_key(
            collection_name=self.collection_name,
            destination=destination,
        )
        try:
            cached = await self.redis.get(key)
            if cached is None:
                return None
            payload = json.loads(cached)
            if not isinstance(payload, list):
                raise ValueError("Invalid cached RAG tips")
            return [_cached_item(destination, item) for item in payload]
        except (TypeError, ValueError):
            await self._delete_cache_key(key)
            return None
        except Exception as exc:
            _log_cache_failure("read_destination_tips", exc)
            return None

    async def _write_tips_cache(
        self,
        destination: str,
        items: list[RetrievedKnowledge],
    ) -> None:
        if self.redis is None:
            return
        payload = [
            {
                "destination": item.destination,
                "text": item.text,
                "title": item.title,
                "source_url": item.source_url,
                "updated_at": item.updated_at.isoformat(),
                "score": item.score,
            }
            for item in items
        ]
        try:
            await self.redis.set(
                destination_tips_cache_key(
                    collection_name=self.collection_name,
                    destination=destination,
                ),
                json.dumps(payload, separators=(",", ":")),
                ex=self.cache_ttl_seconds,
            )
        except Exception as exc:
            _log_cache_failure("write_destination_tips", exc)

    async def _delete_cache_key(self, key: str) -> None:
        if self.redis is None:
            return
        try:
            await self.redis.delete(key)
        except Exception as exc:
            _log_cache_failure("delete_invalid_entry", exc)

    def _validated_items(
        self,
        destination: str,
        hits: list[VectorSearchHit],
    ) -> list[RetrievedKnowledge]:
        items: list[RetrievedKnowledge] = []
        for hit in hits:
            if hit.score < self.score_threshold:
                continue
            payload = hit.payload
            payload_destination = canonical_place_name_for_comparison(
                str(payload.get("destination", ""))
            )
            if payload_destination.casefold() != destination.casefold():
                continue
            try:
                text = _required_payload_text(payload, "text")
                title = plain_text_snippet(
                    _required_payload_text(payload, "title"),
                    limit=200,
                )
                if not title or not plain_text_snippet(text, limit=300):
                    continue
                source_url = validate_public_https_url(
                    _required_payload_text(payload, "source_url")
                )
                updated_at = _payload_date(payload.get("updated_at"))
            except (TypeError, ValueError):
                continue
            items.append(
                RetrievedKnowledge(
                    destination=destination,
                    text=text,
                    title=title,
                    source_url=source_url,
                    updated_at=updated_at,
                    score=hit.score,
                )
            )
        return items


def plain_text_snippet(value: str, *, limit: int) -> str:
    cleaned = html.unescape(value.replace("\x00", " "))
    cleaned = _MARKDOWN_IMAGE_PATTERN.sub(r"\1", cleaned)
    cleaned = _MARKDOWN_LINK_PATTERN.sub(r"\1", cleaned)
    cleaned = _HTML_TAG_PATTERN.sub(" ", cleaned)
    cleaned = _RAW_URL_PATTERN.sub(" ", cleaned)
    cleaned = re.sub(r"[`*_~#>|]+", " ", cleaned)
    cleaned = "".join(
        character
        for character in cleaned
        if unicodedata.category(character) not in {"So", "Sk", "Cs", "Cf"}
    )
    cleaned = " ".join(cleaned.split())
    if len(cleaned) <= limit:
        return cleaned
    prefix = cleaned[: limit - 1].rstrip()
    if " " in prefix:
        prefix = prefix.rsplit(" ", 1)[0]
    return f"{prefix.rstrip()}…"


def _required_payload_text(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"RAG payload field {field} is invalid")
    return value.strip()


def _payload_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    raise TypeError("RAG updated_at payload is invalid")


def _cached_item(destination: str, value: object) -> RetrievedKnowledge:
    if not isinstance(value, dict):
        raise TypeError("Cached RAG tip must be an object")
    payload = cast(dict[str, Any], value)
    cached_destination = canonical_place_name_for_comparison(
        _required_payload_text(payload, "destination")
    )
    if cached_destination.casefold() != destination.casefold():
        raise ValueError("Cached RAG tip destination does not match")
    score = payload.get("score")
    if not isinstance(score, (int, float)):
        raise TypeError("Cached RAG tip score must be numeric")
    return RetrievedKnowledge(
        destination=destination,
        text=_required_payload_text(payload, "text"),
        title=_required_payload_text(payload, "title"),
        source_url=validate_public_https_url(
            _required_payload_text(payload, "source_url")
        ),
        updated_at=_payload_date(payload.get("updated_at")),
        score=float(score),
    )


def _log_cache_failure(operation: str, exc: Exception) -> None:
    logger.warning(
        "RAG cache operation failed",
        extra={
            "request_id": current_request_id(),
            "operation": operation,
            "error_type": type(exc).__name__,
        },
    )


def _elapsed_ms(started_at: float) -> int:
    return max(0, round((perf_counter() - started_at) * 1000))
