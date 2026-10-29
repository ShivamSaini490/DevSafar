from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth_session import AuthSession


class SessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        user_id: UUID,
        sid_hash: str,
        jti_hash: str,
        expires_at: datetime,
    ) -> AuthSession:
        auth_session = AuthSession(
            user_id=user_id,
            sid_hash=sid_hash,
            jti_hash=jti_hash,
            expires_at=expires_at,
        )
        self.session.add(auth_session)
        await self.session.flush()
        return auth_session

    async def get_active(
        self, *, user_id: UUID, sid_hash: str, jti_hash: str, now: datetime
    ) -> AuthSession | None:
        from sqlalchemy import select

        statement = select(AuthSession).where(
            AuthSession.user_id == user_id,
            AuthSession.sid_hash == sid_hash,
            AuthSession.jti_hash == jti_hash,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now,
        )
        return await self.session.scalar(statement)

    async def revoke(self, session_id: UUID, now: datetime) -> bool:
        result = cast(
            CursorResult[Any],
            await self.session.execute(
                update(AuthSession)
                .where(AuthSession.id == session_id, AuthSession.revoked_at.is_(None))
                .values(revoked_at=now)
            ),
        )
        return bool(result.rowcount)

    async def revoke_all(self, user_id: UUID, now: datetime) -> int:
        result = cast(
            CursorResult[Any],
            await self.session.execute(
                update(AuthSession)
                .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
                .values(revoked_at=now)
            ),
        )
        return int(result.rowcount or 0)
