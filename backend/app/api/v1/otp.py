from typing import Annotated, cast

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.dependencies import (
    get_db_session,
    get_redis_client,
    get_request_settings,
)
from app.core.rate_limiter import RateLimitRule, enforce_rate_limit
from app.schemas.otp import (
    EmailRequest,
    GenericOtpResponse,
    ResetGrantResponse,
    ResetPasswordRequest,
    VerifyOtpRequest,
)
from app.services.email_service import (
    EmailSender,
    build_email_sender,
    send_password_reset_otp_safely,
)
from app.services.otp_service import GENERIC_FORGOT_MESSAGE, OtpEmailDelivery, OtpService

router = APIRouter(prefix="/auth", tags=["password-reset"])


def get_email_sender(
    request: Request,
    settings: Annotated[Settings, Depends(get_request_settings)],
) -> EmailSender:
    configured = getattr(request.app.state, "email_sender", None)
    return cast(EmailSender, configured) if configured is not None else build_email_sender(settings)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _queue_otp_email(
    background_tasks: BackgroundTasks,
    delivery: OtpEmailDelivery | None,
    *,
    email_sender: EmailSender,
    request: Request,
    settings: Settings,
) -> None:
    if delivery is None:
        return
    background_tasks.add_task(
        send_password_reset_otp_safely,
        email_sender,
        recipient=delivery.recipient,
        code=delivery.code,
        expires_at=delivery.expires_at,
        request_id=getattr(request.state, "request_id", "unavailable"),
        settings=settings,
    )


async def _limit_otp_request(
    *, request: Request, email: str, redis: Redis, settings: Settings
) -> None:
    window = settings.otp_request_rate_limit_window_seconds
    await enforce_rate_limit(
        redis,
        rule=RateLimitRule("otp-request-ip", settings.otp_request_rate_limit_per_ip, window),
        identity=_client_ip(request),
        settings=settings,
    )
    await enforce_rate_limit(
        redis,
        rule=RateLimitRule("otp-request-email", settings.otp_request_rate_limit_per_email, window),
        identity=email,
        settings=settings,
    )


@router.post("/forgot-password", response_model=GenericOtpResponse)
async def forgot_password(
    payload: EmailRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    redis: Annotated[Redis, Depends(get_redis_client)],
    settings: Annotated[Settings, Depends(get_request_settings)],
    email_sender: Annotated[EmailSender, Depends(get_email_sender)],
) -> GenericOtpResponse:
    await _limit_otp_request(request=request, email=payload.email, redis=redis, settings=settings)
    delivery = await OtpService(db, settings, email_sender).forgot_password(payload.email)
    _queue_otp_email(
        background_tasks,
        delivery,
        email_sender=email_sender,
        request=request,
        settings=settings,
    )
    return GenericOtpResponse(message=GENERIC_FORGOT_MESSAGE)


@router.post("/resend-otp", response_model=GenericOtpResponse)
async def resend_otp(
    payload: EmailRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    redis: Annotated[Redis, Depends(get_redis_client)],
    settings: Annotated[Settings, Depends(get_request_settings)],
    email_sender: Annotated[EmailSender, Depends(get_email_sender)],
) -> GenericOtpResponse:
    await _limit_otp_request(request=request, email=payload.email, redis=redis, settings=settings)
    delivery = await OtpService(db, settings, email_sender).resend(payload.email)
    _queue_otp_email(
        background_tasks,
        delivery,
        email_sender=email_sender,
        request=request,
        settings=settings,
    )
    return GenericOtpResponse(message=GENERIC_FORGOT_MESSAGE)


@router.post("/verify-otp", response_model=ResetGrantResponse)
async def verify_otp(
    payload: VerifyOtpRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    redis: Annotated[Redis, Depends(get_redis_client)],
    settings: Annotated[Settings, Depends(get_request_settings)],
    email_sender: Annotated[EmailSender, Depends(get_email_sender)],
) -> ResetGrantResponse:
    window = settings.otp_verify_rate_limit_window_seconds
    await enforce_rate_limit(
        redis,
        rule=RateLimitRule("otp-verify-ip", settings.otp_verify_rate_limit_per_ip, window),
        identity=_client_ip(request),
        settings=settings,
    )
    await enforce_rate_limit(
        redis,
        rule=RateLimitRule("otp-verify-email", settings.otp_verify_rate_limit_per_email, window),
        identity=payload.email,
        settings=settings,
    )
    grant = await OtpService(db, settings, email_sender).verify(
        email=payload.email, code=payload.code
    )
    return ResetGrantResponse(reset_grant=grant)


@router.post("/reset-password", response_model=GenericOtpResponse)
async def reset_password(
    payload: ResetPasswordRequest,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_request_settings)],
    email_sender: Annotated[EmailSender, Depends(get_email_sender)],
) -> GenericOtpResponse:
    await OtpService(db, settings, email_sender).reset_password(
        reset_grant=payload.reset_grant, new_password=payload.new_password
    )
    return GenericOtpResponse(message="Password reset successful. Please log in again.")
