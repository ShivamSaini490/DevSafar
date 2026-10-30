import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from redis.asyncio import Redis

from app.agents.graph import TripPlanner, TripPlanningFailure
from app.agents.llm import intent_failure_log_fields
from app.core.config import Settings
from app.core.dependencies import (
    AuthContext,
    get_redis_client,
    get_request_settings,
    get_trip_planner,
    require_csrf_if_authenticated,
)
from app.core.exceptions import AppError
from app.schemas.message import TemporaryChatRequest, TemporaryChatResponse
from app.services.temporary_chat_service import TemporaryChatService

router = APIRouter(prefix="/chat", tags=["temporary-chat"])
logger = logging.getLogger(__name__)


@router.post("/temporary", response_model=TemporaryChatResponse)
async def temporary_chat(
    payload: TemporaryChatRequest,
    request: Request,
    _context: Annotated[AuthContext | None, Depends(require_csrf_if_authenticated)],
    redis: Annotated[Redis, Depends(get_redis_client)],
    settings: Annotated[Settings, Depends(get_request_settings)],
    planner: Annotated[TripPlanner, Depends(get_trip_planner)],
) -> TemporaryChatResponse:
    service = TemporaryChatService(redis, settings, planner)
    await service.enforce_limits(
        client_ip=request.client.host if request.client else "unknown",
        temp_session_id=payload.temp_session_id,
    )
    try:
        turn = await service.send_turn(
            temp_session_id=payload.temp_session_id,
            temp_token=payload.temp_token,
            content=payload.content,
        )
    except TripPlanningFailure as exc:
        logger.warning(
            "Temporary trip planning request failed",
            extra={
                "request_id": getattr(request.state, "request_id", "unavailable"),
                **intent_failure_log_fields(exc),
            },
        )
        raise AppError(
            503,
            "trip_planning_unavailable",
            "Trip planning is temporarily unavailable. Please try again.",
        ) from exc
    return TemporaryChatResponse(
        assistant_message=turn.assistant_message,
        temp_token=turn.issued_token,
        context_message_count=turn.context_message_count,
        expires_in_seconds=settings.temporary_chat_ttl_seconds,
        trip=turn.trip,
    )
