import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from argon2.low_level import Type
from email_validator import EmailNotValidError, validate_email
from jwt import ExpiredSignatureError, InvalidTokenError

from app.core.config import Settings

JWT_ALGORITHM = "HS256"
COMMON_PASSWORDS = frozenset(
    {
        "12345678",
        "password",
        "password1",
        "password123",
        "qwerty123",
        "qwertyuiop",
        "123456789",
        "1234567890",
        "abc12345",
        "letmein123",
        "admin123",
        "welcome1",
        "iloveyou",
    }
)

password_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)


@dataclass(frozen=True, slots=True)
class AccessTokenData:
    user_id: UUID
    sid: str
    jti: str
    issued_at: datetime
    expires_at: datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def normalize_email(value: str) -> str:
    try:
        normalized = validate_email(value, check_deliverability=False).normalized
    except EmailNotValidError as exc:
        raise ValueError("Invalid email address") from exc
    return normalized.lower()


def validate_password(value: str) -> str:
    if len(value) < 8:
        raise ValueError("Password must be at least 8 characters")
    if len(value) > 128:
        raise ValueError("Password must be at most 128 characters")
    if value.casefold() in COMMON_PASSWORDS:
        raise ValueError("Password is too common")
    return value


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (InvalidHashError, VerifyMismatchError):
        return False


def generate_session_secret() -> str:
    return secrets.token_urlsafe(32)


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def generate_otp_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def generate_reset_grant() -> str:
    return secrets.token_urlsafe(48)


def keyed_hash(value: str, settings: Settings, *, purpose: str) -> str:
    key = settings.auth_secret.encode("utf-8")
    payload = f"{purpose}:{value}".encode()
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def create_access_token(
    *,
    user_id: UUID,
    sid: str,
    jti: str,
    settings: Settings,
    now: datetime | None = None,
) -> tuple[str, datetime]:
    issued_at = now or utc_now()
    expires_at = issued_at + timedelta(minutes=settings.access_token_minutes)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "sid": sid,
        "jti": jti,
        "iat": issued_at,
        "exp": expires_at,
    }
    token = jwt.encode(
        payload,
        settings.auth_secret,
        algorithm=JWT_ALGORITHM,
    )
    return token, expires_at


def decode_access_token(token: str, settings: Settings) -> AccessTokenData:
    try:
        payload = jwt.decode(
            token,
            settings.auth_secret,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "sid", "jti", "iat", "exp"]},
        )
        return AccessTokenData(
            user_id=UUID(payload["sub"]),
            sid=str(payload["sid"]),
            jti=str(payload["jti"]),
            issued_at=datetime.fromtimestamp(payload["iat"], tz=UTC),
            expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
        )
    except (ExpiredSignatureError, InvalidTokenError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("Invalid or expired access token") from exc
