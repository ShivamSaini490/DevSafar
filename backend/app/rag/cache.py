import hashlib

from redis.asyncio import Redis

RAG_QUERY_VECTOR_CACHE_VERSION = "v1"
RAG_TIPS_COLLECTION_VERSION = "v1"
RAG_QUERY_VECTOR_CACHE_TTL_SECONDS = 30 * 24 * 60 * 60


def query_vector_cache_key(*, model_name: str, destination: str) -> str:
    digest = _digest(model_name, destination)
    return f"devsafar:rag:query-vector:{RAG_QUERY_VECTOR_CACHE_VERSION}:{digest}"


def destination_tips_cache_key(*, collection_name: str, destination: str) -> str:
    digest = _digest(collection_name, destination)
    return f"devsafar:rag:tips:{RAG_TIPS_COLLECTION_VERSION}:{digest}"


async def invalidate_destination_tips(
    redis: Redis,
    *,
    collection_name: str,
    destination: str,
) -> None:
    await redis.delete(
        destination_tips_cache_key(
            collection_name=collection_name,
            destination=destination,
        )
    )


def _digest(namespace: str, destination: str) -> str:
    value = f"{namespace}\x00{destination.casefold().strip()}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
