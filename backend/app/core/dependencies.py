import hmac
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated, cast

from fastapi import Depends, Header, Request
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.exceptions import AppError
from app.core.logging import redact_exception_message
from app.core.security import decode_access_token, keyed_hash, utc_now
from app.models.auth_session import AuthSession
from app.models.user import User
from app.repositories.session_repository import SessionRepository
from app.repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.db_session_factory
    async with session_factory() as session:
        yield session


def get_redis_client(request: Request) -> Redis:
    return cast(Redis, request.app.state.redis)


def get_request_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


@dataclass(frozen=True, slots=True)
class AuthContext:
    user: User
    auth_session: AuthSession


async def get_auth_context(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> AuthContext:
    settings = get_request_settings(request)
    token = request.cookies.get(settings.access_token_cookie_name)
    if token is None:
        raise AppError(401, "authentication_required", "Authentication is required.")
    try:
        claims = decode_access_token(token, settings)
    except ValueError as exc:
        raise AppError(401, "invalid_token", "Invalid or expired access token.") from exc
    auth_session = await SessionRepository(db).get_active(
        user_id=claims.user_id,
        sid_hash=keyed_hash(claims.sid, settings, purpose="sid"),
        jti_hash=keyed_hash(claims.jti, settings, purpose="jti"),
        now=utc_now(),
    )
    user = await UserRepository(db).get_by_id(claims.user_id)
    if auth_session is None or user is None or not user.is_active:
        raise AppError(401, "invalid_session", "Session is no longer valid.")
    return AuthContext(user=user, auth_session=auth_session)


async def require_csrf(
    request: Request,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> AuthContext:
    settings = get_request_settings(request)
    csrf_cookie = request.cookies.get(settings.csrf_cookie_name)
    if not csrf_cookie or not csrf_header or not hmac.compare_digest(csrf_cookie, csrf_header):
        raise AppError(403, "csrf_validation_failed", "CSRF validation failed.")
    return context


async def require_csrf_if_authenticated(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> AuthContext | None:
    """Allow guests, but require a valid session and CSRF token when auth cookie exists."""
    settings = get_request_settings(request)
    if settings.access_token_cookie_name not in request.cookies:
        return None
    context = await get_auth_context(request, db)
    csrf_cookie = request.cookies.get(settings.csrf_cookie_name)
    if not csrf_cookie or not csrf_header or not hmac.compare_digest(csrf_cookie, csrf_header):
        raise AppError(403, "csrf_validation_failed", "CSRF validation failed.")
    return context


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
