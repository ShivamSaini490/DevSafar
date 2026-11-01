
import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Any, Protocol, TypeVar, cast
from uuid import UUID

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models

from app.core.config import Settings
from app.core.logging import current_request_id

logger = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class KnowledgePoint:
    point_id: UUID
    vector: list[float]
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class VectorSearchHit:
    score: float
    payload: dict[str, Any]


class KnowledgeVectorStore(Protocol):
    async def ensure_collection(self) -> None: ...

    async def replace_file_chunks(
        self,
        *,
        file_path: str,
        points: Sequence[KnowledgePoint],
    ) -> None: ...

    async def search(
        self,
        *,
        destination: str,
        vector: list[float],
        top_k: int,
        score_threshold: float,
    ) -> list[VectorSearchHit]: ...


class QdrantVectorStore:
    def __init__(
        self,
        client: AsyncQdrantClient,
        *,
        collection_name: str,
        vector_size: int,
        timeout_seconds: float,
    ) -> None:
        self.client = client
        self.collection_name = collection_name
        self.vector_size = vector_size
        self.timeout_seconds = timeout_seconds
        self._ready = False
        self._ready_lock = asyncio.Lock()

    @classmethod
    def from_settings(cls, settings: Settings, *, vector_size: int) -> "QdrantVectorStore":
        if not settings.qdrant_url or settings.qdrant_api_key is None:
            raise ValueError("Qdrant is not configured")
        client = AsyncQdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key.get_secret_value(),
            timeout=max(1, int(settings.rag_timeout_seconds)),
        )
        return cls(
            client,
            collection_name=settings.qdrant_collection,
            vector_size=vector_size,
            timeout_seconds=settings.rag_timeout_seconds,
        )

    async def ensure_collection(self) -> None:
        if self._ready:
            return
        async with self._ready_lock:
            if self._ready:
                return
            exists = await self._call(
                "collection_exists",
                lambda: self.client.collection_exists(self.collection_name),
            )
            if not exists:
                try:
                    await self._call(
                        "create_collection",
                        lambda: self.client.create_collection(
                            collection_name=self.collection_name,
                            vectors_config=models.VectorParams(
                                size=self.vector_size,
                                distance=models.Distance.COSINE,
                            ),
                        ),
                    )
                except Exception:
                    if not await self._call(
                        "collection_exists_after_create",
                        lambda: self.client.collection_exists(self.collection_name),
                    ):
                        raise
            collection = await self._call(
                "get_collection",
                lambda: self.client.get_collection(self.collection_name),
            )
            vectors = collection.config.params.vectors
            if (
                not isinstance(vectors, models.VectorParams)
                or vectors.size != self.vector_size
                or vectors.distance != models.Distance.COSINE
            ):
                raise ValueError(
                    "Qdrant collection vector configuration does not match RAG settings"
                )
            for field_name in ("destination", "source_url"):
                await self._call(
                    f"create_{field_name}_index",
                    partial(self._create_payload_index, field_name),
                )
            self._ready = True

    async def replace_file_chunks(
        self,
        *,
        file_path: str,
        points: Sequence[KnowledgePoint],
    ) -> None:
        await self.ensure_collection()
        point_ids: list[int | str | UUID] = [point.point_id for point in points]
        if points:
            await self._call(
                "upsert_chunks",
                lambda: self.client.upsert(
                    collection_name=self.collection_name,
                    points=[
                        models.PointStruct(
                            id=point.point_id,
                            vector=point.vector,
                            payload=point.payload,
                        )
                        for point in points
                    ],
                    wait=True,
                ),
            )
        conditions: list[Any] = [
            models.FieldCondition(
                key="file_path",
                match=models.MatchValue(value=file_path),
            )
        ]
        stale_filter = models.Filter(
            must=conditions,
            must_not=(
                [models.HasIdCondition(has_id=point_ids)] if point_ids else None
            ),
        )
        await self._call(
            "delete_stale_chunks",
            lambda: self.client.delete(
                collection_name=self.collection_name,
                points_selector=models.FilterSelector(filter=stale_filter),
                wait=True,
            ),
        )

    async def search(
        self,
        *,
        destination: str,
        vector: list[float],
        top_k: int,
        score_threshold: float,
    ) -> list[VectorSearchHit]:
        await self.ensure_collection()
        response = await self._call(
            "query_points",
            lambda: self.client.query_points(
                collection_name=self.collection_name,
                query=vector,
                query_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="destination",
                            match=models.MatchValue(value=destination),
                        )
                    ]
                ),
                limit=top_k,
                score_threshold=score_threshold,
                with_payload=True,
                with_vectors=False,
            ),
        )
        return [
            VectorSearchHit(
                score=float(point.score),
                payload=cast(dict[str, Any], point.payload or {}),
            )
            for point in response.points
        ]

    async def delete_collection(self) -> None:
        await self._call(
            "delete_collection",
            lambda: self.client.delete_collection(self.collection_name),
        )
        self._ready = False

    async def _create_payload_index(self, field_name: str) -> None:
        await self.client.create_payload_index(
            collection_name=self.collection_name,
            field_name=field_name,
            field_schema=models.PayloadSchemaType.KEYWORD,
            wait=True,
        )

    async def close(self) -> None:
        await self.client.close()

    async def _call(self, operation: str, call: Callable[[], Awaitable[T]]) -> T:
        for attempt in range(2):
            try:
                async with asyncio.timeout(self.timeout_seconds):
                    return await call()
            except Exception as exc:
                logger.warning(
                    "Qdrant operation failed",
                    extra={
                        "request_id": current_request_id(),
                        "operation": operation,
                        "attempt": attempt + 1,
                        "error_type": type(exc).__name__,
                    },
                )
                if attempt == 1:
                    raise
        raise RuntimeError("Unreachable Qdrant retry state")
