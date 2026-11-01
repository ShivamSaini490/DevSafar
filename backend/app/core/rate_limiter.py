import hashlib
import hmac
import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID

from redis.asyncio import Redis

from app.core.config import Settings
from app.core.exceptions import AppError
from app.core.logging import current_request_id

logger = logging.getLogger(__name__)

RATE_LIMIT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
local ttl = redis.call('TTL', KEYS[1])
return {count, ttl}
"""

MULTI_RATE_LIMIT_SCRIPT = """
for index, key in ipairs(KEYS) do
  local current = tonumber(redis.call('GET', key) or '0')
  local limit = tonumber(ARGV[(index - 1) * 2 + 1])
  if current >= limit then
    local ttl = redis.call('TTL', key)
    if ttl < 1 then ttl = tonumber(ARGV[(index - 1) * 2 + 2]) end
    return {0, ttl}
  end
end
for index, key in ipairs(KEYS) do
  local count = redis.call('INCR', key)
  if count == 1 then
    redis.call('EXPIRE', key, ARGV[(index - 1) * 2 + 2])
  end
end
return {1, 0}
"""

GLOBAL_ACQUIRE_SCRIPT = """
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
if current >= tonumber(ARGV[1]) then return 0 end
local count = redis.call('INCR', KEYS[1])
redis.call('EXPIRE', KEYS[1], ARGV[2])
return count
"""

GLOBAL_RELEASE_SCRIPT = """
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
if current <= 1 then redis.call('DEL', KEYS[1]); return 0 end
return redis.call('DECR', KEYS[1])
"""

DAILY_BUDGET_SCRIPT = """
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
if current >= tonumber(ARGV[1]) then return {0, current} end
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[2]) end
return {1, count}
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


def _hashed_key(prefix: str, identity: str, settings: Settings) -> str:
    digest = hmac.new(
        settings.auth_secret.encode(),
        identity.casefold().encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{prefix}:{digest}"


@dataclass(slots=True)
class PlanningLease:
    redis: Redis
    global_key: str
    active_key: str | None
    released: bool = False

    async def release(self) -> None:
        if self.released:
            return
        self.released = True
        await self.redis.eval(GLOBAL_RELEASE_SCRIPT, 1, self.global_key)
        if self.active_key is not None:
            await self.redis.delete(self.active_key)


class PlanningAdmissionService:
    GLOBAL_KEY = "planning:active:global"

    def __init__(self, redis: Redis, settings: Settings) -> None:
        self.redis = redis
        self.settings = settings
        self._lease_ttl = math.ceil(
            settings.graph_timeout_seconds + settings.planning_stream_max_seconds + 30
        )

    async def admit_saved(self, user_id: UUID) -> PlanningLease:
        identity = str(user_id)
        active_key = _hashed_key("planning:active:user", identity, self.settings)
        acquired = await self.redis.set(active_key, "1", ex=self._lease_ttl, nx=True)
        if not acquired:
            raise AppError(
                409,
                "planning_already_running",
                "A planning run is already active for this account.",
            )
        lease: PlanningLease | None = None
        try:
            lease = await self._acquire_global(active_key=active_key)
            await self._consume_limits(
                keys=(
                    _hashed_key("planning:quota:user-hour", identity, self.settings),
                    _hashed_key("planning:quota:user-day", identity, self.settings),
                ),
                limits=(
                    (self.settings.planning_runs_per_hour, 3600),
                    (self.settings.planning_runs_per_day, 86400),
                ),
            )
            return lease
        except Exception:
            if lease is None:
                await self.redis.delete(active_key)
            else:
                await lease.release()
            raise

    async def admit_temporary(self, *, client_ip: str, temp_session_id: str) -> PlanningLease:
        lease = await self._acquire_global(active_key=None)
        try:
            await self._consume_limits(
                keys=(
                    _hashed_key("planning:quota:guest-hour", client_ip, self.settings),
                    _hashed_key("planning:quota:temp-session", temp_session_id, self.settings),
                ),
                limits=(
                    (self.settings.planning_runs_per_hour_guest, 3600),
                    (
                        self.settings.planning_runs_per_temp_session,
                        self.settings.temporary_chat_ttl_seconds,
                    ),
                ),
            )
            return lease
        except Exception:
            await lease.release()
            raise

    async def _acquire_global(self, *, active_key: str | None) -> PlanningLease:
        acquired = await self.redis.eval(
            GLOBAL_ACQUIRE_SCRIPT,
            1,
            self.GLOBAL_KEY,
            self.settings.planning_max_concurrent,
            self._lease_ttl,
        )
        if not int(acquired):
            raise AppError(
                429,
                "planning_capacity_reached",
                "Planning capacity is busy. Please try again shortly.",
                headers={"Retry-After": "1"},
            )
        return PlanningLease(self.redis, self.GLOBAL_KEY, active_key)

    async def _consume_limits(
        self,
        *,
        keys: tuple[str, ...],
        limits: tuple[tuple[int, int], ...],
    ) -> None:
        arguments = [value for limit in limits for value in limit]
        result = await self.redis.eval(
            MULTI_RATE_LIMIT_SCRIPT,
            len(keys),
            *keys,
            *arguments,
        )
        if not int(result[0]):
            raise AppError(
                429,
                "planning_rate_limit_exceeded",
                "Planning limit reached. Please try again later.",
                headers={"Retry-After": str(max(1, int(result[1])))},
            )


class ExternalCallBudget(Protocol):
    async def consume(self, service: Literal["groq", "tavily"]) -> bool: ...


class RedisExternalCallBudget:
    def __init__(self, redis: Redis, settings: Settings) -> None:
        self.redis = redis
        self.settings = settings

    async def consume(self, service: Literal["groq", "tavily"]) -> bool:
        limit = (
            self.settings.groq_daily_call_budget
            if service == "groq"
            else self.settings.tavily_daily_search_budget
        )
        if limit == 0:
            return True
        now = datetime.now(UTC)
        expires_in = max(
            1,
            math.ceil(
                (
                    datetime.combine(
                        now.date() + timedelta(days=1),
                        datetime.min.time(),
                        tzinfo=UTC,
                    )
                    - now
                ).total_seconds()
            ),
        )
        key = f"external-budget:{service}:{now.date().isoformat()}"
        result = await self.redis.eval(
            DAILY_BUDGET_SCRIPT,
            1,
            key,
            limit,
            expires_in,
        )
        allowed, count = bool(int(result[0])), int(result[1])
        logger.info(
            "External service daily budget count",
            extra={
                "request_id": current_request_id(),
                "service": service,
                "count": count,
                "limit": limit,
                "allowed": allowed,
            },
        )
        return allowed
