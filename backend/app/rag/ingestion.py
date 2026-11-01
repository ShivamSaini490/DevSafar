
import hashlib
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from uuid import UUID

from redis.asyncio import Redis

from app.core.logging import current_request_id
from app.rag.cache import invalidate_destination_tips
from app.rag.embeddings import EmbeddingProvider
from app.rag.vector_store import KnowledgePoint, KnowledgeVectorStore
from app.schemas.trip import canonical_place_name_for_comparison
from app.utils.url_validator import validate_public_https_url

REQUIRED_FRONT_MATTER = {
    "title",
    "destination",
    "source_url",
    "updated_at",
    "license_note",
}
logger = logging.getLogger(__name__)


class KnowledgeDocumentError(ValueError):
    """A curated knowledge document is invalid and must not be ingested."""


@dataclass(frozen=True, slots=True)
class KnowledgeDocument:
    file_path: str
    title: str
    destination: str
    source_url: str
    updated_at: date
    license_note: str
    body: str
    example: bool


@dataclass(frozen=True, slots=True)
class KnowledgeChunk:
    point_id: UUID
    file_path: str
    chunk_index: int
    title: str
    destination: str
    source_url: str
    updated_at: date
    license_note: str
    text: str

    def payload(self) -> dict[str, object]:
        return {
            "file_path": self.file_path,
            "chunk_index": self.chunk_index,
            "title": self.title,
            "destination": self.destination,
            "source_url": self.source_url,
            "updated_at": self.updated_at.isoformat(),
            "license_note": self.license_note,
            "text": self.text,
        }


@dataclass(frozen=True, slots=True)
class IngestionStats:
    documents: int = 0
    chunks: int = 0
    skipped_examples: int = 0


def load_document(path: Path, *, documents_root: Path) -> KnowledgeDocument:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise KnowledgeDocumentError("Knowledge document could not be read") from exc
    metadata, body = _parse_front_matter(raw)
    missing = sorted(REQUIRED_FRONT_MATTER - metadata.keys())
    if missing:
        raise KnowledgeDocumentError(
            f"Missing required front matter: {', '.join(missing)}"
        )
    title = _required_value(metadata, "title")
    destination = canonical_place_name_for_comparison(
        _required_value(metadata, "destination")
    )
    source_url = validate_public_https_url(_required_value(metadata, "source_url"))
    updated_at = _parse_updated_at(_required_value(metadata, "updated_at"))
    license_note = _required_value(metadata, "license_note")
    example = _parse_boolean(metadata.get("example", "false"), field="example")
    if not body.strip() and not example:
        raise KnowledgeDocumentError("Knowledge document body must not be empty")
    try:
        relative_path = path.resolve().relative_to(documents_root.resolve()).as_posix()
    except ValueError as exc:
        raise KnowledgeDocumentError("Knowledge document is outside the documents root") from exc
    return KnowledgeDocument(
        file_path=relative_path,
        title=title,
        destination=destination,
        source_url=source_url,
        updated_at=updated_at,
        license_note=license_note,
        body=body.strip(),
        example=example,
    )


def chunk_document(
    document: KnowledgeDocument,
    *,
    max_chars: int = 900,
    overlap_chars: int = 120,
) -> list[KnowledgeChunk]:
    if max_chars < 100:
        raise ValueError("max_chars must be at least 100")
    if overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be non-negative and smaller than max_chars")
    chunks: list[KnowledgeChunk] = []
    for heading, section_body in _markdown_sections(document.body):
        prefix = f"{heading}\n" if heading else ""
        body_limit = max(20, max_chars - len(prefix))
        for body_chunk in _chunk_text(
            section_body,
            max_chars=body_limit,
            overlap_chars=min(overlap_chars, body_limit - 1),
        ):
            text = f"{prefix}{body_chunk}".strip()
            chunk_index = len(chunks)
            chunks.append(
                KnowledgeChunk(
                    point_id=deterministic_point_id(document.file_path, chunk_index),
                    file_path=document.file_path,
                    chunk_index=chunk_index,
                    title=document.title,
                    destination=document.destination,
                    source_url=document.source_url,
                    updated_at=document.updated_at,
                    license_note=document.license_note,
                    text=text,
                )
            )
    return chunks


def deterministic_point_id(file_path: str, chunk_index: int) -> UUID:
    digest = hashlib.sha256(f"{file_path}:{chunk_index}".encode()).digest()
    return UUID(bytes=digest[:16])


class KnowledgeIngestor:
    def __init__(
        self,
        embedder: EmbeddingProvider,
        vector_store: KnowledgeVectorStore,
        *,
        max_chars: int = 900,
        overlap_chars: int = 120,
        redis: Redis | None = None,
        collection_name: str | None = None,
    ) -> None:
        self.embedder = embedder
        self.vector_store = vector_store
        self.max_chars = max_chars
        self.overlap_chars = overlap_chars
        self.redis = redis
        self.collection_name = collection_name

    async def ingest_directory(
        self,
        documents_root: Path,
        *,
        dry_run: bool = False,
    ) -> IngestionStats:
        stats, prepared = _prepare_directory(
            documents_root,
            max_chars=self.max_chars,
            overlap_chars=self.overlap_chars,
        )
        if dry_run:
            return stats
        await self.vector_store.ensure_collection()
        for document, chunks in prepared:
            vectors = await self.embedder.embed_documents([chunk.text for chunk in chunks])
            if len(vectors) != len(chunks):
                raise RuntimeError("Embedding count does not match knowledge chunk count")
            points = [
                KnowledgePoint(
                    point_id=chunk.point_id,
                    vector=vector,
                    payload=chunk.payload(),
                )
                for chunk, vector in zip(chunks, vectors, strict=True)
            ]
            await self.vector_store.replace_file_chunks(
                file_path=document.file_path,
                points=points,
            )
            await self._invalidate_destination_cache(document.destination)
        return stats

    async def _invalidate_destination_cache(self, destination: str) -> None:
        if self.redis is None or self.collection_name is None:
            return
        try:
            await invalidate_destination_tips(
                self.redis,
                collection_name=self.collection_name,
                destination=destination,
            )
        except Exception as exc:
            logger.warning(
                "RAG destination cache invalidation failed",
                extra={
                    "request_id": current_request_id(),
                    "error_type": type(exc).__name__,
                },
            )


def inspect_directory(
    documents_root: Path,
    *,
    max_chars: int = 900,
    overlap_chars: int = 120,
) -> IngestionStats:
    stats, _prepared = _prepare_directory(
        documents_root,
        max_chars=max_chars,
        overlap_chars=overlap_chars,
    )
    return stats


def _prepare_directory(
    documents_root: Path,
    *,
    max_chars: int,
    overlap_chars: int,
) -> tuple[IngestionStats, list[tuple[KnowledgeDocument, list[KnowledgeChunk]]]]:
    documents = 0
    chunk_count = 0
    skipped_examples = 0
    prepared: list[tuple[KnowledgeDocument, list[KnowledgeChunk]]] = []
    for path in sorted(documents_root.glob("*.md")):
        if path.name.casefold() == "readme.md":
            continue
        document = load_document(path, documents_root=documents_root)
        if document.example:
            skipped_examples += 1
            continue
        chunks = chunk_document(
            document,
            max_chars=max_chars,
            overlap_chars=overlap_chars,
        )
        documents += 1
        chunk_count += len(chunks)
        prepared.append((document, chunks))
    return IngestionStats(documents, chunk_count, skipped_examples), prepared


def _parse_front_matter(raw: str) -> tuple[dict[str, str], str]:
    lines = raw.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        raise KnowledgeDocumentError("Knowledge document requires YAML front matter")
    try:
        end_index = next(
            index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"
        )
    except StopIteration as exc:
        raise KnowledgeDocumentError("Knowledge document front matter is not closed") from exc
    metadata: dict[str, str] = {}
    for line in lines[1:end_index]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, separator, value = stripped.partition(":")
        if not separator or not key.strip():
            raise KnowledgeDocumentError("Front matter must use key: value entries")
        normalized_key = key.strip().casefold()
        if normalized_key in metadata:
            raise KnowledgeDocumentError("Front matter keys must be unique")
        metadata[normalized_key] = _unquote(value.strip())
    return metadata, "\n".join(lines[end_index + 1 :]).strip()


def _required_value(metadata: dict[str, str], field: str) -> str:
    value = metadata.get(field, "").strip()
    if not value:
        raise KnowledgeDocumentError(f"Front matter field {field} must not be empty")
    return value


def _parse_updated_at(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError as exc:
            raise KnowledgeDocumentError("updated_at must be an ISO date or datetime") from exc


def _parse_boolean(value: str, *, field: str) -> bool:
    normalized = value.strip().casefold()
    if normalized in {"true", "yes", "1"}:
        return True
    if normalized in {"false", "no", "0"}:
        return False
    raise KnowledgeDocumentError(f"{field} must be true or false")


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _markdown_sections(markdown: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    heading = ""
    body_lines: list[str] = []
    for line in markdown.splitlines():
        if line.lstrip().startswith("#"):
            if body_lines or heading:
                sections.append((heading, "\n".join(body_lines).strip()))
            heading = line.strip()
            body_lines = []
        else:
            body_lines.append(line)
    if body_lines or heading:
        sections.append((heading, "\n".join(body_lines).strip()))
    return [(current_heading, body) for current_heading, body in sections if body]


def _chunk_text(text: str, *, max_chars: int, overlap_chars: int) -> Sequence[str]:
    normalized = " ".join(text.split())
    if not normalized:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(len(normalized), start + max_chars)
        if end < len(normalized):
            boundary = normalized.rfind(" ", start + max_chars // 2, end)
            if boundary > start:
                end = boundary
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(normalized):
            break
        next_start = max(start + 1, end - overlap_chars)
        whitespace = normalized.find(" ", next_start)
        start = whitespace + 1 if whitespace != -1 and whitespace < end else next_start
    return chunks
