import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager, suppress
from datetime import datetime
from uuid import uuid4

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.agents.graph import LangGraphTripPlanner
from app.agents.llm import GroqAttractionExtractor
from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.exceptions import handle_unexpected_exception, register_exception_handlers
from app.core.logging import bind_request_id, configure_logging, reset_request_id
from app.core.rate_limiter import RedisExternalCallBudget
from app.db.session import create_db_engine, create_redis_client, create_session_factory
from app.integrations.base import ProviderBundle
from app.integrations.maps_provider import OsmMapsProvider
from app.integrations.tavily_provider import TavilyAttractionsProvider
from app.rag.embeddings import FastEmbedService
from app.rag.retriever import RAGRetriever
from app.rag.vector_store import QdrantVectorStore
from app.tasks.cleanup_tasks import run_cleanup_loop

logger = logging.getLogger(__name__)


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        request_id_token = bind_request_id(request_id)
        response_started = False
        path = str(scope.get("path", ""))

        raw_content_length = next(
            (
                value
                for name, value in scope.get("headers", [])
                if name.lower() == b"content-length"
            ),
            None,
        )
        try:
            content_length = int(raw_content_length) if raw_content_length is not None else 0
        except ValueError:
            content_length = 0

        async def send_with_request_id(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                headers["X-Content-Type-Options"] = "nosniff"
                headers["Referrer-Policy"] = "no-referrer"
                headers["X-Frame-Options"] = "DENY"
                if path in {"/docs", "/redoc", "/openapi.json"}:
                    headers["Content-Security-Policy"] = "frame-ancestors 'none'"
                if path.startswith("/api/") or headers.get("content-type", "").startswith(
                    "text/event-stream"
                ):
                    headers["Cache-Control"] = "no-store"
            await send(message)

        try:
            if content_length > self.settings.max_request_body_bytes:
                response = JSONResponse(
                    status_code=413,
                    content={
                        "error": {
                            "code": "request_body_too_large",
                            "message": "Request body is too large.",
                            "request_id": request_id,
                        }
                    },
                )
                await response(scope, receive, send_with_request_id)
            else:
                await self.app(scope, receive, send_with_request_id)
        except Exception as exc:
            if response_started:
                raise
            response = handle_unexpected_exception(Request(scope), exc)
            await response(scope, receive, send_with_request_id)
        finally:
            reset_request_id(request_id_token)


def _lifespan(settings: Settings) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_db_engine(settings)
        redis = create_redis_client(settings)

        app.state.settings = settings
        app.state.db_engine = engine
        session_factory = create_session_factory(engine)
        app.state.db_session_factory = session_factory
        app.state.redis = redis
        external_call_budget = RedisExternalCallBudget(redis, settings)
        app.state.external_call_budget = external_call_budget
        provider_http_client: httpx.AsyncClient | None = None
        attraction_extractor: GroqAttractionExtractor | None = None
        rag_store: QdrantVectorStore | None = None
        rag_warmup_task: asyncio.Task[None] | None = None
        rag_embedder: FastEmbedService | None = None
        if settings.rag_enabled:
            rag_embedder = FastEmbedService(
                settings.embedding_model,
                load_timeout_seconds=settings.rag_model_load_timeout_seconds,
                cache_dir=settings.embedding_cache_dir,
            )
            rag_warmup_task = rag_embedder.start_warmup()
            app.state.rag_embedder = rag_embedder
        if not hasattr(app.state, "trip_planner"):
            rag_retriever: RAGRetriever | None = None
            if settings.rag_configured:
                assert rag_embedder is not None
                rag_store = QdrantVectorStore.from_settings(
                    settings,
                    vector_size=rag_embedder.dimension,
                )
                rag_retriever = RAGRetriever(
                    rag_embedder,
                    rag_store,
                    top_k=settings.rag_top_k,
                    score_threshold=settings.rag_score_threshold,
                    timeout_seconds=settings.rag_timeout_seconds,
                    redis=redis,
                    model_name=settings.embedding_model,
                    collection_name=settings.qdrant_collection,
                    cache_ttl_seconds=settings.rag_cache_ttl_seconds,
                )
                app.state.rag_store = rag_store
            if settings.maps_provider == "osm" or settings.tavily_configured:
                provider_http_client = httpx.AsyncClient()
            if settings.tavily_configured:
                attraction_extractor = GroqAttractionExtractor(
                    settings,
                    call_budget=external_call_budget,
                )

            if settings.maps_provider == "osm":
                assert provider_http_client is not None
                osm_maps_provider = OsmMapsProvider(
                    settings,
                    redis,
                    client=provider_http_client,
                )

                def provider_factory(fetched_at: datetime) -> ProviderBundle:
                    bundle = ProviderBundle.stubs(fetched_at).with_maps(
                        osm_maps_provider,
                        source_name="osrm",
                    )
                    if settings.tavily_configured:
                        assert attraction_extractor is not None
                        bundle = bundle.with_places(
                            TavilyAttractionsProvider(
                                settings,
                                redis,
                                fetched_at=fetched_at,
                                extractor=attraction_extractor,
                                client=provider_http_client,
                                call_budget=external_call_budget,
                            ),
                            source_name="tavily",
                        )
                    return bundle

                app.state.trip_planner = LangGraphTripPlanner(
                    settings,
                    provider_factory=provider_factory,
                    call_budget=external_call_budget,
                    rag_retriever=rag_retriever,
                )
            elif settings.tavily_configured:
                assert provider_http_client is not None
                assert attraction_extractor is not None

                def tavily_provider_factory(fetched_at: datetime) -> ProviderBundle:
                    return ProviderBundle.stubs(fetched_at).with_places(
                        TavilyAttractionsProvider(
                            settings,
                            redis,
                            fetched_at=fetched_at,
                            extractor=attraction_extractor,
                            client=provider_http_client,
                            call_budget=external_call_budget,
                        ),
                        source_name="tavily",
                    )

                app.state.trip_planner = LangGraphTripPlanner(
                    settings,
                    provider_factory=tavily_provider_factory,
                    call_budget=external_call_budget,
                    rag_retriever=rag_retriever,
                )
            else:
                app.state.trip_planner = LangGraphTripPlanner(
                    settings,
                    call_budget=external_call_budget,
                    rag_retriever=rag_retriever,
                )
        cleanup_task: asyncio.Task[None] | None = None
        if settings.cleanup_enabled:
            cleanup_task = asyncio.create_task(
                run_cleanup_loop(session_factory, redis, settings),
                name="expired-conversation-cleanup",
            )

        try:
            yield
        finally:
            if cleanup_task is not None:
                cleanup_task.cancel()
                with suppress(asyncio.CancelledError):
                    await cleanup_task
            if provider_http_client is not None:
                await provider_http_client.aclose()
            if rag_warmup_task is not None and not rag_warmup_task.done():
                rag_warmup_task.cancel()
                with suppress(asyncio.CancelledError):
                    await rag_warmup_task
            if rag_store is not None:
                await rag_store.close()
            await redis.aclose()
            await engine.dispose()

    return lifespan


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    configure_logging(app_settings.log_level)
    if app_settings.uses_ephemeral_auth_secret:
        logger.warning(
            "SECRET_KEY is not configured; using an ephemeral development key. "
            "Authentication sessions will be invalid after restart."
        )
    for smtp_warning in app_settings.smtp_configuration_warnings():
        logger.warning(smtp_warning)
    for tavily_warning in app_settings.tavily_configuration_warnings():
        logger.warning(tavily_warning)
    for rag_warning in app_settings.rag_configuration_warnings():
        logger.warning(rag_warning)

    application = FastAPI(
        title=app_settings.app_name,
        version=app_settings.app_version,
        debug=app_settings.debug,
        lifespan=_lifespan(app_settings),
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token", "Last-Event-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )
    application.add_middleware(RequestIdMiddleware, settings=app_settings)
    register_exception_handlers(application)
    application.include_router(api_router)
    return application


app = create_app()
