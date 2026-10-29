import logging
from datetime import datetime
from email.message import EmailMessage
from typing import Protocol

import aiosmtplib

from app.core.config import Settings
from app.core.exceptions import AppError

logger = logging.getLogger(__name__)


class EmailSender(Protocol):
    async def send_password_reset_otp(
        self, *, recipient: str, code: str, expires_at: datetime
    ) -> None: ...


class SmtpEmailSender:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def send_password_reset_otp(
        self, *, recipient: str, code: str, expires_at: datetime
    ) -> None:
        settings = self.settings
        if not settings.smtp_host or not settings.smtp_from_email:
            raise AppError(503, "email_unavailable", "Email delivery is not configured.")
        message = EmailMessage()
        message["From"] = settings.smtp_from_email
        message["To"] = recipient
        message["Subject"] = "Password reset code"
        message.set_content(
            f"{code}\nExpires at: {expires_at.isoformat()}\n"
            "Ignore this email if you did not request it."
        )
        await aiosmtplib.send(
            message,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password.get_secret_value() if settings.smtp_password else None,
            start_tls=settings.smtp_use_tls,
        )


class DevelopmentOtpEmailFallback:
    async def send_password_reset_otp(
        self, *, recipient: str, code: str, expires_at: datetime
    ) -> None:
        del recipient, code, expires_at
        logger.info("OTP email skipped")


def build_email_sender(settings: Settings) -> EmailSender:
    if settings.smtp_host and settings.smtp_from_email:
        return SmtpEmailSender(settings)
    if settings.environment == "development" and settings.dev_otp_email_fallback_enabled:
        return DevelopmentOtpEmailFallback()
    return SmtpEmailSender(settings)
