from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings

PLANNING_STREAM_SOCKET_TIMEOUT_MARGIN_SECONDS = 2.0


def _without_socket_timeout_query(connection_url: str) -> str:
    parsed = urlsplit(connection_url)
    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key.casefold() not in {"socket_timeout", "socket_connect_timeout"}
        ]
    )
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment))


def create_db_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        echo=settings.debug,
        hide_parameters=True,
        pool_pre_ping=True,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


def create_redis_client(settings: Settings) -> Redis:
    return Redis.from_url(
        _without_socket_timeout_query(settings.redis_connection_url),
        decode_responses=True,
        health_check_interval=30,
        socket_timeout=settings.redis_socket_timeout_seconds,
    )


def create_planning_stream_redis_client(
    settings: Settings,
    *,
    block_seconds: float,
) -> Redis:
    """Create a dedicated client whose read timeout always exceeds XREAD BLOCK."""

    socket_timeout = max(
        settings.redis_socket_timeout_seconds,
        block_seconds + PLANNING_STREAM_SOCKET_TIMEOUT_MARGIN_SECONDS,
    )
    return Redis.from_url(
        _without_socket_timeout_query(settings.redis_connection_url),
        decode_responses=True,
        health_check_interval=30,
        socket_timeout=socket_timeout,
        socket_connect_timeout=min(socket_timeout, 10.0),
    )
