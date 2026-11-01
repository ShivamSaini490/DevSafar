
import asyncio
from collections.abc import Sequence
from typing import Protocol, cast

from fastembed import TextEmbedding


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
    """Lazy, process-local FastEmbed model with non-blocking async methods."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._dimension = embedding_dimension(model_name)
        self._model: TextEmbedding | None = None
        self._load_lock = asyncio.Lock()

    @property
    def dimension(self) -> int:
        return self._dimension

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
        if self._model is not None:
            return self._model
        async with self._load_lock:
            if self._model is None:
                self._model = await asyncio.to_thread(
                    TextEmbedding,
                    model_name=self.model_name,
                )
        return self._model

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
