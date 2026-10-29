from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.password_reset_otp import PasswordResetOtp


class OtpRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_for_user(
        self, user_id: UUID, *, for_update: bool = False
    ) -> PasswordResetOtp | None:
        statement = select(PasswordResetOtp).where(PasswordResetOtp.user_id == user_id)
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def issue(
        self,
        *,
        user_id: UUID,
        otp_hash: str,
        expires_at: datetime,
        resend_available_at: datetime,
    ) -> PasswordResetOtp:
        record = await self.get_for_user(user_id, for_update=True)
        values = {
            "otp_hash": otp_hash,
            "attempts": 0,
            "expires_at": expires_at,
            "resend_available_at": resend_available_at,
            "consumed_at": None,
            "reset_grant_hash": None,
            "reset_grant_expires_at": None,
            "reset_grant_consumed_at": None,
        }
        if record is None:
            record = PasswordResetOtp(user_id=user_id, **values)
            self.session.add(record)
        else:
            for key, value in values.items():
                setattr(record, key, value)
        await self.session.flush()
        return record

    async def verify_and_grant(
        self,
        *,
        user_id: UUID,
        otp_hash: str,
        grant_hash: str,
        grant_expires_at: datetime,
        now: datetime,
        max_attempts: int,
    ) -> bool:
        result = cast(
            CursorResult[Any],
            await self.session.execute(
                update(PasswordResetOtp)
                .where(
                    PasswordResetOtp.user_id == user_id,
                    PasswordResetOtp.otp_hash == otp_hash,
                    PasswordResetOtp.consumed_at.is_(None),
                    PasswordResetOtp.expires_at > now,
                    PasswordResetOtp.attempts < max_attempts,
                )
                .values(
                    consumed_at=now,
                    reset_grant_hash=grant_hash,
                    reset_grant_expires_at=grant_expires_at,
                )
            ),
        )
        return bool(result.rowcount)

    async def record_failed_attempt(
        self, *, user_id: UUID, now: datetime, max_attempts: int
    ) -> bool:
        result = cast(
            CursorResult[Any],
            await self.session.execute(
                update(PasswordResetOtp)
                .where(
                    PasswordResetOtp.user_id == user_id,
                    PasswordResetOtp.consumed_at.is_(None),
                    PasswordResetOtp.expires_at > now,
                    PasswordResetOtp.attempts < max_attempts,
                )
                .values(attempts=PasswordResetOtp.attempts + 1)
            ),
        )
        return bool(result.rowcount)

    async def consume_grant(self, *, grant_hash: str, now: datetime) -> UUID | None:
        result = await self.session.execute(
            update(PasswordResetOtp)
            .where(
                PasswordResetOtp.reset_grant_hash == grant_hash,
                PasswordResetOtp.reset_grant_consumed_at.is_(None),
                PasswordResetOtp.reset_grant_expires_at > now,
            )
            .values(reset_grant_consumed_at=now)
            .returning(PasswordResetOtp.user_id)
        )
        return result.scalar_one_or_none()

    async def delete_for_user(self, user_id: UUID) -> None:
        await self.session.execute(
            delete(PasswordResetOtp).where(PasswordResetOtp.user_id == user_id)
        )
