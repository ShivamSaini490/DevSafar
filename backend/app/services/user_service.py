from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.security import hash_password, utc_now, verify_password
from app.models.user import User
from app.repositories.session_repository import SessionRepository
from app.repositories.user_repository import UserRepository


class UserService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.users = UserRepository(db)
        self.sessions = SessionRepository(db)

    async def update(self, user: User, *, name: str | None, email: str | None) -> User:
        if name is not None:
            user.name = name
        if email is not None:
            existing = await self.users.get_by_email(email)
            if existing is not None and existing.id != user.id:
                raise AppError(409, "email_already_registered", "Email is already registered.")
            user.email = email
        try:
            await self.db.commit()
            await self.db.refresh(user)
            return user
        except IntegrityError as exc:
            await self.db.rollback()
            raise AppError(409, "email_already_registered", "Email is already registered.") from exc

    async def change_password(
        self, user: User, *, current_password: str, new_password: str
    ) -> None:
        if not verify_password(current_password, user.password_hash):
            raise AppError(400, "invalid_password", "Current password is incorrect.")
        user.password_hash = hash_password(new_password)
        await self.sessions.revoke_all(user.id, utc_now())
        await self.db.commit()

    async def delete_account(self, user: User, *, password: str) -> None:
        if not verify_password(password, user.password_hash):
            raise AppError(400, "invalid_password", "Password is incorrect.")
        await self.users.delete(user)
        await self.db.commit()
