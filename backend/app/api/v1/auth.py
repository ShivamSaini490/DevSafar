from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.dependencies import (
    AuthContext,
    get_db_session,
    get_redis_client,
    get_request_settings,
    require_csrf,
)
from app.core.rate_limiter import RateLimitRule, enforce_rate_limit
from app.schemas.auth import AuthResponse, LoginRequest, SignupRequest
from app.schemas.user import MessageResponse, UserResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    payload: SignupRequest,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_request_settings)],
) -> UserResponse:
    user = await AuthService(db, settings).signup(
        name=payload.name, email=payload.email, password=payload.password
    )
    return UserResponse.model_validate(user)


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    redis: Annotated[Redis, Depends(get_redis_client)],
    settings: Annotated[Settings, Depends(get_request_settings)],
) -> AuthResponse:
    window = settings.login_rate_limit_window_seconds
    await enforce_rate_limit(
        redis,
        rule=RateLimitRule("login-ip", settings.login_rate_limit_per_ip, window),
        identity=_client_ip(request),
        settings=settings,
    )
    await enforce_rate_limit(
        redis,
        rule=RateLimitRule("login-email", settings.login_rate_limit_per_email, window),
        identity=payload.email,
        settings=settings,
    )
    result = await AuthService(db, settings).login(email=payload.email, password=payload.password)
    response.set_cookie(
        settings.access_token_cookie_name,
        result.access_token,
        httponly=True,
        secure=settings.secure_auth_cookies,
        samesite="lax",
        max_age=settings.access_token_minutes * 60,
        path="/",
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        result.csrf_token,
        httponly=False,
        secure=settings.secure_auth_cookies,
        samesite="lax",
        max_age=settings.access_token_minutes * 60,
        path="/",
    )
    return AuthResponse(user=UserResponse.model_validate(result.user))


@router.post("/logout", response_model=MessageResponse)
async def logout(
    response: Response,
    context: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_request_settings)],
) -> MessageResponse:
    await AuthService(db, settings).logout(context.auth_session)
    response.delete_cookie(settings.access_token_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")
    return MessageResponse(message="Logged out.")
