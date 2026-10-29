import hashlib
import hmac
from dataclasses import dataclass

from redis.asyncio import Redis

from app.core.config import Settings
from app.core.exceptions import AppError

RATE_LIMIT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
local ttl = redis.call('TTL', KEYS[1])
return {count, ttl}
"""


@dataclass(frozen=True, slots=True)
class RateLimitRule:
    name: str
    limit: int
    window_seconds: int


def _safe_key(rule: RateLimitRule, identity: str, settings: Settings) -> str:
    digest = hmac.new(
        settings.auth_secret.encode(),
        identity.casefold().encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"rate-limit:{rule.name}:{digest}"


async def enforce_rate_limit(
    redis: Redis, *, rule: RateLimitRule, identity: str, settings: Settings
) -> None:
    result = await redis.eval(
        RATE_LIMIT_SCRIPT, 1, _safe_key(rule, identity, settings), rule.window_seconds
    )
    count, ttl = int(result[0]), max(1, int(result[1]))
    if count > rule.limit:
        raise AppError(
            status_code=429,
            code="rate_limit_exceeded",
            message="Too many requests. Please try again later.",
            headers={"Retry-After": str(ttl)},
        )
