import hashlib
import hmac
import json
import logging
import re
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.graph import (
    ProgressStage,
    ProgressStatus,
    TripPlanner,
    TripPlanningFailure,
)
from app.core.config import Settings
from app.core.exceptions import AppError
from app.core.logging import bind_request_id, reset_request_id
from app.core.rate_limiter import PlanningLease
from app.core.tracing import temporary_chat_tracing_enabled
from app.schemas.trip import TripResponse
from app.services.chat_service import ChatService
from app.services.temporary_chat_service import (
    PreparedTemporaryTurn,
    TemporaryChatService,
)

logger = logging.getLogger(__name__)

FAILED_TIMEOUT_MESSAGE = "Trip planning timed out. Please try again."
FAILED_INTENT_BUDGET_MESSAGE = (
    "Trip planning capacity is unavailable right now. Please try later."
)
FAILED_UNAVAILABLE_MESSAGE = "Trip planning failed safely. Please try again."
FAILED_EXPIRED_MESSAGE = "Planning result is no longer available."
FAILED_INTERRUPTED_MESSAGE = "Planning stopped before completion. Please start a new run."
_STREAM_ID_PATTERN = re.compile(r"^\d+-\d+$")

TERMINAL_EVENT_SCRIPT = """
local existing = redis.call('HGET', KEYS[2], 'terminal_id')
if existing then return existing end
local event_id = redis.call(
  'XADD', KEYS[1], 'MAXLEN', '=', ARGV[2], '*', 'payload', ARGV[1]
)
redis.call('EXPIRE', KEYS[1], ARGV[3])
redis.call('HSET', KEYS[2], 'terminal_id', event_id)
redis.call('EXPIRE', KEYS[2], ARGV[3])
return event_id
"""


class PlanningStreamStore:
    def __init__(self, redis: Redis, settings: Settings) -> None:
        self.redis = redis
        self.settings = settings

    async def create_saved(
        self,
        *,
        trip_id: UUID,
        conversation_id: UUID,
        owner_id: UUID,
    ) -> None:
        await self._create(
            trip_id,
            {
                "mode": "saved",
                "conversation_id": str(conversation_id),
                "owner_id": str(owner_id),
            },
        )

    async def create_temporary(
        self,
        *,
        trip_id: UUID,
        temp_session_id: str,
        temp_token: str,
    ) -> None:
        await self._create(
            trip_id,
            {
                "mode": "temporary",
                "temp_binding": self.temporary_binding(temp_session_id, temp_token),
            },
        )

    async def _create(self, trip_id: UUID, values: dict[str, str]) -> None:
        metadata: dict[str, str] = {
            **values,
            "trip_id": str(trip_id),
            "created_at": datetime.now(UTC).isoformat(),
        }
        key = self.metadata_key(trip_id)
        await self.redis.hset(key, mapping=metadata)  # type: ignore[arg-type]
        await self.redis.expire(key, self.settings.planning_stream_ttl_seconds)

    async def metadata(self, trip_id: UUID) -> dict[str, str] | None:
        values = await self.redis.hgetall(self.metadata_key(trip_id))
        return cast(dict[str, str], values) if values else None

    async def publish_progress(
        self,
        trip_id: UUID,
        stage: ProgressStage,
        status: ProgressStatus,
    ) -> None:
        await self._publish(
            trip_id,
            {
                "event": "progress",
                "stage": stage,
                "status": status,
                "ts": datetime.now(UTC).isoformat(),
            },
        )

    async def publish_completed(
        self,
        trip_id: UUID,
        *,
        trip: TripResponse | None = None,
    ) -> str:
        event: dict[str, object] = {"event": "completed", "trip_id": str(trip_id)}
        if trip is not None:
            event["trip"] = trip.model_dump(mode="json")
        return await self._publish(trip_id, event, terminal=True)

    async def publish_failed(self, trip_id: UUID, *, code: str, message: str) -> str:
        return await self._publish(
            trip_id,
            {"event": "failed", "code": code, "message": message},
            terminal=True,
        )

    async def _publish(
        self,
        trip_id: UUID,
        event: dict[str, object],
        *,
        terminal: bool = False,
    ) -> str:
        payload = json.dumps(event, separators=(",", ":"), ensure_ascii=True)
        stream_key = self.stream_key(trip_id)
        metadata_key = self.metadata_key(trip_id)
        if terminal:
            event_id = await self.redis.eval(
                TERMINAL_EVENT_SCRIPT,
                2,
                stream_key,
                metadata_key,
                payload,
                100,
                self.settings.planning_stream_ttl_seconds,
            )
            return cast(str, event_id)
        event_id = await self.redis.xadd(
            stream_key,
            {"payload": payload},
            maxlen=100,
            approximate=False,
        )
        await self.redis.expire(stream_key, self.settings.planning_stream_ttl_seconds)
        await self.redis.expire(
            metadata_key, self.settings.planning_stream_ttl_seconds
        )
        return cast(str, event_id)

    async def event_stream(
        self,
        trip_id: UUID,
        *,
        last_event_id: str | None,
    ) -> AsyncIterator[str]:
        metadata = await self.metadata(trip_id)
        if metadata is None:
            return
        cursor = (
            last_event_id
            if last_event_id and _STREAM_ID_PATTERN.fullmatch(last_event_id)
            else "0-0"
        )
        terminal_id = metadata.get("terminal_id")
        if terminal_id is not None and cursor == terminal_id:
            return
        created_at = datetime.fromisoformat(metadata["created_at"])
        expires_at = created_at.timestamp() + self.settings.planning_stream_max_seconds
        stream_key = self.stream_key(trip_id)
        while True:
            remaining = expires_at - time.time()
            if remaining <= 0:
                await self.publish_failed(
                    trip_id,
                    code="planning_interrupted",
                    message=FAILED_INTERRUPTED_MESSAGE,
                )
                rows = cast(
                    list[tuple[str, list[tuple[str, dict[str, str]]]]],
                    await self.redis.xread({stream_key: cursor}, count=100),
                )
                for _key, entries in rows:
                    for event_id, fields in entries:
                        cursor = event_id
                        payload = fields["payload"]
                        yield f"id: {cursor}\ndata: {payload}\n\n"
                        event = json.loads(payload)
                        if event.get("event") in {"completed", "failed"}:
                            return
                return
            block_seconds = min(
                float(self.settings.planning_stream_heartbeat_seconds),
                remaining,
            )
            rows = cast(
                list[tuple[str, list[tuple[str, dict[str, str]]]]],
                await self.redis.xread(
                    {stream_key: cursor},
                    count=100,
                    block=max(1, int(block_seconds * 1000)),
                ),
            )
            if not rows:
                yield ": heartbeat\n\n"
                continue
            for _key, entries in rows:
                for event_id, fields in entries:
                    cursor = event_id
                    payload = fields["payload"]
                    yield f"id: {cursor}\ndata: {payload}\n\n"
                    event = json.loads(payload)
                    if event.get("event") in {"completed", "failed"}:
                        return

    def temporary_binding(self, temp_session_id: str, temp_token: str) -> str:
        return hmac.new(
            self.settings.auth_secret.encode(),
            f"{temp_session_id}:{temp_token}".encode(),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _digest(trip_id: UUID) -> str:
        return hashlib.sha256(str(trip_id).encode()).hexdigest()

    @classmethod
    def stream_key(cls, trip_id: UUID) -> str:
        return f"planning:stream:{cls._digest(trip_id)}"

    @classmethod
    def metadata_key(cls, trip_id: UUID) -> str:
        return f"planning:metadata:{cls._digest(trip_id)}"


class AsyncPlanningService:
    def __init__(
        self,
        *,
        redis: Redis,
        settings: Settings,
        planner: TripPlanner,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.redis = redis
        self.settings = settings
        self.planner = planner
        self.session_factory = session_factory
        self.streams = PlanningStreamStore(redis, settings)

    async def run_saved(
        self,
        *,
        trip_id: UUID,
        conversation_id: UUID,
        owner_id: UUID,
        content: str,
        previous_trip: TripResponse | None,
        lease: PlanningLease,
        request_id: str,
    ) -> None:
        token = bind_request_id(request_id)
        try:
            trip = await self.planner.run(
                conversation_id=conversation_id,
                user_prompt=content,
                previous_trip=previous_trip,
                chat_mode="saved",
                trip_id=trip_id,
                progress_callback=lambda stage, status: self.streams.publish_progress(
                    trip_id, stage, status
                ),
            )
            async with self.session_factory() as db:
                await ChatService(db).complete_async_turn(
                    conversation_id=conversation_id,
                    owner_id=owner_id,
                    trip=trip,
                )
            await self.streams.publish_completed(trip_id)
        except AppError as exc:
            await self.streams.publish_failed(
                trip_id,
                code="planning_result_expired",
                message=FAILED_EXPIRED_MESSAGE,
            )
            self._log_failure(request_id, type(exc).__name__, "planning_result_expired")
        except TripPlanningFailure as exc:
            await self._publish_planning_failure(trip_id, exc)
            self._log_failure(request_id, type(exc).__name__, exc.code)
        except Exception as exc:
            await self.streams.publish_failed(
                trip_id,
                code="trip_planning_unavailable",
                message=FAILED_UNAVAILABLE_MESSAGE,
            )
            self._log_failure(request_id, type(exc).__name__, "trip_planning_unavailable")
        finally:
            await lease.release()
            reset_request_id(token)

    async def run_temporary(
        self,
        *,
        trip_id: UUID,
        temp_session_id: str,
        content: str,
        prepared: PreparedTemporaryTurn,
        lease: PlanningLease,
        request_id: str,
    ) -> None:
        token = bind_request_id(request_id)
        try:
            temporary_chat_tracing_enabled(self.settings)
            trip = await self.planner.run(
                conversation_id=None,
                user_prompt=content,
                previous_trip=prepared.previous_trip,
                chat_mode="temporary",
                trip_id=trip_id,
                progress_callback=lambda stage, status: self.streams.publish_progress(
                    trip_id, stage, status
                ),
            )
            await TemporaryChatService(
                self.redis,
                self.settings,
                self.planner,
            ).complete_turn(
                temp_session_id=temp_session_id,
                content=content,
                prepared=prepared,
                trip=trip,
            )
            await self.streams.publish_completed(trip_id, trip=trip)
        except TripPlanningFailure as exc:
            await self._publish_planning_failure(trip_id, exc)
            self._log_failure(request_id, type(exc).__name__, exc.code)
        except Exception as exc:
            await self.streams.publish_failed(
                trip_id,
                code="trip_planning_unavailable",
                message=FAILED_UNAVAILABLE_MESSAGE,
            )
            self._log_failure(request_id, type(exc).__name__, "trip_planning_unavailable")
        finally:
            await lease.release()
            reset_request_id(token)

    async def _publish_planning_failure(
        self,
        trip_id: UUID,
        exc: TripPlanningFailure,
    ) -> None:
        safe_failures = {
            "planning_timeout": FAILED_TIMEOUT_MESSAGE,
            "planning_intent_budget_exhausted": FAILED_INTENT_BUDGET_MESSAGE,
        }
        code = exc.code if exc.code in safe_failures else "trip_planning_unavailable"
        message = safe_failures.get(exc.code, FAILED_UNAVAILABLE_MESSAGE)
        await self.streams.publish_failed(trip_id, code=code, message=message)

    @staticmethod
    def _log_failure(request_id: str, error_type: str, code: str) -> None:
        logger.warning(
            "Background trip planning failed",
            extra={
                "request_id": request_id,
                "error_type": error_type,
                "code": code,
            },
        )
