import logging
from collections.abc import AsyncIterator
from typing import cast

from fastapi import Request
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.logging import redact_exception_message

logger = logging.getLogger(__name__)


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.db_session_factory
    async with session_factory() as session:
        yield session


def get_redis_client(request: Request) -> Redis:
    return cast(Redis, request.app.state.redis)


async def postgres_is_ready(request: Request) -> bool:
    engine: AsyncEngine = request.app.state.db_engine
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as exc:  # readiness must convert dependency failures into a safe status
        settings = cast(Settings, request.app.state.settings)
        logger.warning(
            "PostgreSQL readiness check failed",
            extra={
                "error_type": type(exc).__name__,
                "error_message": redact_exception_message(
                    exc,
                    secret_values=(settings.postgres_password.get_secret_value(),),
                ),
            },
        )
        return False
    return True


async def redis_is_ready(request: Request) -> bool:
    client: Redis = request.app.state.redis
    try:
        return bool(await client.ping())
    except Exception as exc:  # readiness must convert dependency failures into a safe status
        logger.warning(
            "Redis readiness check failed",
            extra={
                "error_type": type(exc).__name__,
                "error_message": redact_exception_message(exc),
            },
        )
        return False
