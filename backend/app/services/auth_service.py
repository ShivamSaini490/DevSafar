from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AppError
from app.core.security import (
    create_access_token,
    generate_csrf_token,
    generate_session_secret,
    hash_password,
    keyed_hash,
    utc_now,
    verify_password,
)
from app.models.auth_session import AuthSession
from app.models.user import User
from app.repositories.session_repository import SessionRepository
from app.repositories.user_repository import UserRepository

DUMMY_PASSWORD_HASH = hash_password("not-a-real-user-password")


@dataclass(frozen=True, slots=True)
class LoginResult:
    user: User
    auth_session: AuthSession
    access_token: str
    csrf_token: str


class AuthService:
    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.users = UserRepository(db)
        self.sessions = SessionRepository(db)

    async def signup(self, *, name: str, email: str, password: str) -> User:
        if await self.users.get_by_email(email):
            raise AppError(409, "email_already_registered", "Email is already registered.")
        try:
            user = await self.users.create(
                name=name, email=email, password_hash=hash_password(password)
            )
            await self.db.commit()
            await self.db.refresh(user)
            return user
        except IntegrityError as exc:
            await self.db.rollback()
            raise AppError(409, "email_already_registered", "Email is already registered.") from exc

    async def login(self, *, email: str, password: str) -> LoginResult:
        user = await self.users.get_by_email(email)
        password_hash = user.password_hash if user is not None else DUMMY_PASSWORD_HASH
        valid = verify_password(password, password_hash)
        if user is None or not valid or not user.is_active:
            raise AppError(401, "invalid_credentials", "Invalid email or password.")
        sid, jti = generate_session_secret(), generate_session_secret()
        token, expires_at = create_access_token(
            user_id=user.id, sid=sid, jti=jti, settings=self.settings
        )
        auth_session = await self.sessions.create(
            user_id=user.id,
            sid_hash=keyed_hash(sid, self.settings, purpose="sid"),
            jti_hash=keyed_hash(jti, self.settings, purpose="jti"),
            expires_at=expires_at,
        )
        await self.db.commit()
        return LoginResult(user, auth_session, token, generate_csrf_token())

    async def logout(self, auth_session: AuthSession) -> None:
        await self.sessions.revoke(auth_session.id, utc_now())
        await self.db.commit()
