import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager, suppress
from uuid import uuid4

from fastapi import FastAPI, Request
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.exceptions import handle_unexpected_exception, register_exception_handlers
from app.core.logging import configure_logging
from app.db.session import create_db_engine, create_redis_client, create_session_factory
from app.tasks.cleanup_tasks import run_cleanup_loop

logger = logging.getLogger(__name__)


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        response_started = False

        async def send_with_request_id(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                headers = MutableHeaders(scope=message)
                headers.append("X-Request-ID", request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception as exc:
            if response_started:
                raise
            response = handle_unexpected_exception(Request(scope), exc)
            await response(scope, receive, send_with_request_id)


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
        cleanup_task: asyncio.Task[None] | None = None
        if settings.cleanup_enabled:
            cleanup_task = asyncio.create_task(
                run_cleanup_loop(session_factory, settings),
                name="expired-conversation-cleanup",
            )

        try:
            yield
        finally:
            if cleanup_task is not None:
                cleanup_task.cancel()
                with suppress(asyncio.CancelledError):
                    await cleanup_task
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

    application = FastAPI(
        title=app_settings.app_name,
        version=app_settings.app_version,
        debug=app_settings.debug,
        lifespan=_lifespan(app_settings),
    )
    application.add_middleware(RequestIdMiddleware)
    register_exception_handlers(application)
    application.include_router(api_router)
    return application


app = create_app()
