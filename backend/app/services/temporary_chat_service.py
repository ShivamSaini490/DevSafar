
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from typing import Literal, TypedDict, cast

from redis.asyncio import Redis

from app.core.config import Settings
from app.core.constants import PLACEHOLDER_ASSISTANT_REPLY
from app.core.exceptions import AppError
from app.core.rate_limiter import RateLimitRule, enforce_rate_limit

TEMPORARY_CHAT_KEY_PREFIX = "devsafar:temp-chat:v1"


class TemporaryMessage(TypedDict):
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class TemporaryChatTurn:
    assistant_message: str
    issued_token: str | None
    context_message_count: int


def temporary_chat_tracing_enabled(_settings: Settings) -> Literal[False]:
    """Hard safety boundary for the future graph integration."""
    return False


class TemporaryChatService:
    def __init__(self, redis: Redis, settings: Settings) -> None:
        self.redis = redis
        self.settings = settings

    async def enforce_limits(self, *, client_ip: str, temp_session_id: str) -> None:
        window = self.settings.temporary_chat_rate_limit_window_seconds
        await enforce_rate_limit(
            self.redis,
            rule=RateLimitRule(
                "temporary-chat-ip",
                self.settings.temporary_chat_rate_limit_per_ip,
                window,
            ),
            identity=client_ip,
            settings=self.settings,
        )
        await enforce_rate_limit(
            self.redis,
            rule=RateLimitRule(
                "temporary-chat-session",
                self.settings.temporary_chat_rate_limit_per_session,
                window,
            ),
            identity=temp_session_id,
            settings=self.settings,
        )

    async def send_turn(
        self,
        *,
        temp_session_id: str,
        temp_token: str | None,
        content: str,
    ) -> TemporaryChatTurn:
        issued_token: str | None = None
        if temp_token is None:
            temp_token = secrets.token_urlsafe(32)
            issued_token = temp_token
            messages: list[TemporaryMessage] = []
        else:
            raw_context = await self.redis.get(self._context_key(temp_session_id, temp_token))
            if raw_context is None:
                raise AppError(404, "temporary_chat_not_found", "Temporary chat not found.")
            messages = self._decode_context(cast(str, raw_context))

        messages.extend(
            (
                TemporaryMessage(role="user", content=content),
                TemporaryMessage(role="assistant", content=PLACEHOLDER_ASSISTANT_REPLY),
            )
        )
        messages = self._bounded_messages(messages)
        serialized = self._serialize_context(messages)
        await self.redis.set(
            self._context_key(temp_session_id, temp_token),
            serialized,
            ex=self.settings.temporary_chat_ttl_seconds,
        )
        return TemporaryChatTurn(
            assistant_message=PLACEHOLDER_ASSISTANT_REPLY,
            issued_token=issued_token,
            context_message_count=len(messages),
        )

    def _context_key(self, temp_session_id: str, temp_token: str) -> str:
        payload = f"{temp_session_id}:{temp_token}".encode()
        digest = hmac.new(
            self.settings.auth_secret.encode(), payload, hashlib.sha256
        ).hexdigest()
        return f"{TEMPORARY_CHAT_KEY_PREFIX}:{digest}"

    def _bounded_messages(
        self, messages: list[TemporaryMessage]
    ) -> list[TemporaryMessage]:
        bounded = messages[-self.settings.temporary_chat_max_messages :]
        if bounded and bounded[0]["role"] == "assistant":
            bounded = bounded[1:]
        while len(bounded) > 2 and len(self._serialize_context(bounded).encode()) > (
            self.settings.temporary_chat_max_bytes
        ):
            bounded = bounded[2:]
        if len(self._serialize_context(bounded).encode()) > self.settings.temporary_chat_max_bytes:
            raise AppError(413, "temporary_chat_context_too_large", "Message is too large.")
        return bounded

    @staticmethod
    def _serialize_context(messages: list[TemporaryMessage]) -> str:
        return json.dumps({"messages": messages}, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _decode_context(raw_context: str) -> list[TemporaryMessage]:
        try:
            decoded = json.loads(raw_context)
            messages = decoded["messages"]
            if not isinstance(messages, list):
                raise TypeError
            return cast(list[TemporaryMessage], messages)
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise AppError(
                404, "temporary_chat_not_found", "Temporary chat not found."
            ) from exc
