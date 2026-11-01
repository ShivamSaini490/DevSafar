import hmac
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.dependencies import (
    AuthContext,
    get_db_session,
    get_optional_auth_context,
    get_redis_client,
    get_request_settings,
)
from app.core.exceptions import AppError
from app.services.conversation_service import ConversationService
from app.services.planning_service import PlanningStreamStore

router = APIRouter(prefix="/trips", tags=["trip-events"])


@router.get("/{trip_id}/events")
async def trip_events(
    trip_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    redis: Annotated[Redis, Depends(get_redis_client)],
    settings: Annotated[Settings, Depends(get_request_settings)],
    context: Annotated[AuthContext | None, Depends(get_optional_auth_context)],
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    temp_session_id: Annotated[str | None, Query(min_length=32, max_length=128)] = None,
    temp_token: Annotated[str | None, Query(min_length=32, max_length=128)] = None,
) -> StreamingResponse:
    streams = PlanningStreamStore(redis, settings)
    metadata = await streams.metadata(trip_id)
    if metadata is None:
        raise AppError(404, "planning_stream_not_found", "Planning stream not found.")
    if metadata.get("mode") == "saved":
        if context is None or metadata.get("owner_id") != str(context.user.id):
            raise AppError(404, "planning_stream_not_found", "Planning stream not found.")
        try:
            conversation_id = UUID(metadata["conversation_id"])
        except (KeyError, ValueError) as exc:
            raise AppError(404, "planning_stream_not_found", "Planning stream not found.") from exc
        await ConversationService(db).get_required(
            conversation_id=conversation_id,
            owner_id=context.user.id,
        )
    elif metadata.get("mode") == "temporary":
        if temp_session_id is None or temp_token is None:
            raise AppError(404, "planning_stream_not_found", "Planning stream not found.")
        supplied = streams.temporary_binding(temp_session_id, temp_token)
        if not hmac.compare_digest(supplied, metadata.get("temp_binding", "")):
            raise AppError(404, "planning_stream_not_found", "Planning stream not found.")
    else:
        raise AppError(404, "planning_stream_not_found", "Planning stream not found.")

    return StreamingResponse(
        streams.event_stream(trip_id, last_event_id=last_event_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
