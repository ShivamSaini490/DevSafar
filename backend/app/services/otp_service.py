import asyncio
from datetime import timedelta
from time import monotonic

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AppError
from app.core.security import (
    generate_otp_code,
    generate_reset_grant,
    hash_password,
    keyed_hash,
    utc_now,
)
from app.repositories.otp_repository import OtpRepository
from app.repositories.session_repository import SessionRepository
from app.repositories.user_repository import UserRepository
from app.services.email_service import EmailSender

GENERIC_FORGOT_MESSAGE = "If an account exists, a password reset code has been sent."
MINIMUM_FORGOT_RESPONSE_SECONDS = 0.2


class OtpService:
    def __init__(self, db: AsyncSession, settings: Settings, email_sender: EmailSender) -> None:
        self.db = db
        self.settings = settings
        self.email_sender = email_sender
        self.users = UserRepository(db)
        self.otps = OtpRepository(db)
        self.sessions = SessionRepository(db)

    async def forgot_password(self, email: str) -> str:
        started = monotonic()
        code = generate_otp_code()
        code_hash = keyed_hash(code, self.settings, purpose="otp")
        user = await self.users.get_by_email(email)
        if user is not None:
            now = utc_now()
            expires_at = now + timedelta(minutes=self.settings.otp_expiry_minutes)
            await self.otps.issue(
                user_id=user.id,
                otp_hash=code_hash,
                expires_at=expires_at,
                resend_available_at=now
                + timedelta(seconds=self.settings.otp_resend_cooldown_seconds),
            )
            await self.db.commit()
            await self.email_sender.send_password_reset_otp(
                recipient=user.email, code=code, expires_at=expires_at
            )
        remaining = MINIMUM_FORGOT_RESPONSE_SECONDS - (monotonic() - started)
        if remaining > 0:
            await asyncio.sleep(remaining)
        return GENERIC_FORGOT_MESSAGE

    async def resend(self, email: str) -> str:
        user = await self.users.get_by_email(email)
        if user is None:
            return GENERIC_FORGOT_MESSAGE
        now = utc_now()
        record = await self.otps.get_for_user(user.id, for_update=True)
        if record is not None and record.resend_available_at > now:
            retry = max(1, int((record.resend_available_at - now).total_seconds()))
            raise AppError(
                429,
                "otp_resend_cooldown",
                "Please wait before requesting another code.",
                headers={"Retry-After": str(retry)},
            )
        code = generate_otp_code()
        expires_at = now + timedelta(minutes=self.settings.otp_expiry_minutes)
        await self.otps.issue(
            user_id=user.id,
            otp_hash=keyed_hash(code, self.settings, purpose="otp"),
            expires_at=expires_at,
            resend_available_at=now + timedelta(seconds=self.settings.otp_resend_cooldown_seconds),
        )
        await self.db.commit()
        await self.email_sender.send_password_reset_otp(
            recipient=user.email, code=code, expires_at=expires_at
        )
        return GENERIC_FORGOT_MESSAGE

    async def verify(self, *, email: str, code: str) -> str:
        user = await self.users.get_by_email(email)
        if user is None:
            raise AppError(400, "invalid_otp", "The code is invalid or expired.")
        now = utc_now()
        grant = generate_reset_grant()
        verified = await self.otps.verify_and_grant(
            user_id=user.id,
            otp_hash=keyed_hash(code, self.settings, purpose="otp"),
            grant_hash=keyed_hash(grant, self.settings, purpose="reset-grant"),
            grant_expires_at=now + timedelta(minutes=self.settings.reset_grant_expiry_minutes),
            now=now,
            max_attempts=self.settings.otp_max_attempts,
        )
        if not verified:
            await self.otps.record_failed_attempt(
                user_id=user.id, now=now, max_attempts=self.settings.otp_max_attempts
            )
            await self.db.commit()
            raise AppError(400, "invalid_otp", "The code is invalid or expired.")
        await self.db.commit()
        return grant

    async def reset_password(self, *, reset_grant: str, new_password: str) -> None:
        now = utc_now()
        user_id = await self.otps.consume_grant(
            grant_hash=keyed_hash(reset_grant, self.settings, purpose="reset-grant"), now=now
        )
        if user_id is None:
            raise AppError(400, "invalid_reset_grant", "Reset grant is invalid or expired.")
        user = await self.users.get_by_id(user_id)
        if user is None:
            raise AppError(400, "invalid_reset_grant", "Reset grant is invalid or expired.")
        user.password_hash = hash_password(new_password)
        await self.sessions.revoke_all(user.id, now)
        await self.db.commit()
