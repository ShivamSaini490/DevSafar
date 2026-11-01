
import argparse
import asyncio
import sys
from pathlib import Path

SCRIPT_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_BACKEND_ROOT))

from app.core.config import BACKEND_ROOT, get_settings  # noqa: E402
from app.db.session import create_redis_client  # noqa: E402
from app.rag.embeddings import FastEmbedService  # noqa: E402
from app.rag.ingestion import (  # noqa: E402
    IngestionStats,
    KnowledgeIngestor,
    inspect_directory,
)
from app.rag.vector_store import QdrantVectorStore  # noqa: E402

DEFAULT_DOCUMENTS_DIR = BACKEND_ROOT / "app" / "rag" / "documents"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest curated DevSafar RAG documents.")
    parser.add_argument(
        "--documents-dir",
        type=Path,
        default=DEFAULT_DOCUMENTS_DIR,
        help="Markdown directory (defaults to app/rag/documents).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and count files without embeddings or Qdrant writes.",
    )
    return parser.parse_args()


async def _run(documents_dir: Path) -> IngestionStats:
    settings = get_settings()
    if not settings.qdrant_url or settings.qdrant_api_key is None:
        raise SystemExit("Qdrant configuration is required for ingestion")
    embedder = FastEmbedService(
        settings.embedding_model,
        load_timeout_seconds=settings.rag_model_load_timeout_seconds,
        cache_dir=settings.embedding_cache_dir,
    )
    redis = create_redis_client(settings)
    store = QdrantVectorStore.from_settings(
        settings,
        vector_size=embedder.dimension,
    )
    try:
        return await KnowledgeIngestor(
            embedder,
            store,
            redis=redis,
            collection_name=settings.qdrant_collection,
        ).ingest_directory(documents_dir)
    finally:
        await store.close()
        await redis.aclose()


def main() -> None:
    arguments = _arguments()
    documents_dir = arguments.documents_dir.resolve()
    stats = (
        inspect_directory(documents_dir)
        if arguments.dry_run
        else asyncio.run(_run(documents_dir))
    )
    print(
        f"documents={stats.documents} chunks={stats.chunks} "
        f"skipped_examples={stats.skipped_examples}"
    )


if __name__ == "__main__":
    main()
