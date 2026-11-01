
import asyncio
import html
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol

from pydantic import HttpUrl, TypeAdapter

from app.core.logging import current_request_id
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
    ) -> None:
        self.embedder = embedder
        self.vector_store = vector_store
        self.top_k = top_k
        self.score_threshold = score_threshold
        self.timeout_seconds = timeout_seconds

    async def retrieve(self, destination: str) -> RetrievalResult:
        canonical_destination = canonical_place_name_for_comparison(destination)
        query = f"{canonical_destination}: {RAG_QUERY_INTENT}"
        try:
            async with asyncio.timeout(self.timeout_seconds):
                vector = await self.embedder.embed_query(query)
                hits = await self.vector_store.search(
                    destination=canonical_destination,
                    vector=vector,
                    top_k=self.top_k,
                    score_threshold=self.score_threshold,
                )
            items = self._validated_items(canonical_destination, hits)
            return RetrievalResult(items=items[: self.top_k], degraded=False)
        except Exception as exc:
            logger.warning(
                "RAG retrieval failed; continuing without destination knowledge",
                extra={
                    "request_id": current_request_id(),
                    "error_type": type(exc).__name__,
                },
            )
            return RetrievalResult(items=[], degraded=True)

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
