
import asyncio
import logging
from collections.abc import Sequence
from time import perf_counter
from typing import Literal, Protocol, cast

from fastembed import TextEmbedding

from app.core.logging import current_request_id

logger = logging.getLogger(__name__)
EmbeddingModelState = Literal["not_ready", "ready", "failed"]


class EmbeddingProvider(Protocol):
    @property
    def dimension(self) -> int: ...

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


def embedding_dimension(model_name: str) -> int:
    for model in TextEmbedding.list_supported_models():
        if model["model"] == model_name:
            return int(model["dim"])
    raise ValueError("EMBEDDING_MODEL is not supported by FastEmbed")


class FastEmbedService:
    """One process-local FastEmbed model with a shared background load task."""

    def __init__(
        self,
        model_name: str,
        *,
        load_timeout_seconds: float = 180.0,
        cache_dir: str | None = None,
    ) -> None:
        self.model_name = model_name
        self.load_timeout_seconds = load_timeout_seconds
        self.cache_dir = cache_dir
        self._dimension = embedding_dimension(model_name)
        self._model: TextEmbedding | None = None
        self._load_lock = asyncio.Lock()
        self._load_task: asyncio.Task[None] | None = None
        self._state: EmbeddingModelState = "not_ready"
        self._load_error_type: str | None = None

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def state(self) -> EmbeddingModelState:
        return self._state

    @property
    def load_error_type(self) -> str | None:
        return self._load_error_type

    def start_warmup(self) -> asyncio.Task[None]:
        if self._load_task is None:
            self._load_task = asyncio.create_task(
                self._load_once(),
                name="rag-embedding-model-warmup",
            )
        return self._load_task

    async def ensure_ready(self) -> None:
        task = self.start_warmup()
        await asyncio.shield(task)
        if self._state != "ready":
            raise RuntimeError("RAG embedding model is unavailable")

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        values = list(texts)
        if not values:
            return []
        model = await self._get_model()
        return await asyncio.to_thread(self._embed_documents_sync, model, values)

    async def embed_query(self, text: str) -> list[float]:
        model = await self._get_model()
        return await asyncio.to_thread(self._embed_query_sync, model, text)

    async def _get_model(self) -> TextEmbedding:
        await self.ensure_ready()
        if self._model is None:
            raise RuntimeError("RAG embedding model is unavailable")
        return self._model

    async def _load_once(self) -> None:
        async with self._load_lock:
            if self._state in {"ready", "failed"}:
                return
            started_at = perf_counter()
            try:
                async with asyncio.timeout(self.load_timeout_seconds):
                    if self.cache_dir is None:
                        model = await asyncio.to_thread(
                            self._load_model_sync,
                            self.model_name,
                        )
                    else:
                        model = await asyncio.to_thread(
                            self._load_model_sync,
                            self.model_name,
                            self.cache_dir,
                        )
            except TimeoutError:
                self._state = "failed"
                self._load_error_type = "TimeoutError"
                logger.warning(
                    "RAG operation timed out",
                    extra={
                        "request_id": current_request_id(),
                        "stage": "model_load",
                        "elapsed_ms": _elapsed_ms(started_at),
                    },
                )
                return
            except Exception as exc:
                self._state = "failed"
                self._load_error_type = type(exc).__name__
                logger.warning(
                    "RAG embedding model load failed",
                    extra={
                        "request_id": current_request_id(),
                        "error_type": type(exc).__name__,
                    },
                )
                return
            self._model = model
            self._state = "ready"

    @staticmethod
    def _load_model_sync(model_name: str, cache_dir: str | None = None) -> TextEmbedding:
        return TextEmbedding(model_name=model_name, cache_dir=cache_dir)

    @staticmethod
    def _embed_documents_sync(
        model: TextEmbedding,
        texts: list[str],
    ) -> list[list[float]]:
        return [embedding.tolist() for embedding in model.embed(texts)]

    @staticmethod
    def _embed_query_sync(model: TextEmbedding, text: str) -> list[float]:
        embeddings = list(model.query_embed(text))
        if len(embeddings) != 1:
            raise RuntimeError("FastEmbed returned an unexpected query embedding count")
        return cast(list[float], embeddings[0].tolist())


def _elapsed_ms(started_at: float) -> int:
    return max(0, round((perf_counter() - started_at) * 1000))
