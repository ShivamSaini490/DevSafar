
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from redis.asyncio import Redis

from app.core.config import Settings
from app.core.dependencies import (
    AuthContext,
    get_redis_client,
    get_request_settings,
    require_csrf_if_authenticated,
)
from app.schemas.message import TemporaryChatRequest, TemporaryChatResponse
from app.services.temporary_chat_service import TemporaryChatService

router = APIRouter(prefix="/chat", tags=["temporary-chat"])


@router.post("/temporary", response_model=TemporaryChatResponse)
async def temporary_chat(
    payload: TemporaryChatRequest,
    request: Request,
    _context: Annotated[AuthContext | None, Depends(require_csrf_if_authenticated)],
    redis: Annotated[Redis, Depends(get_redis_client)],
    settings: Annotated[Settings, Depends(get_request_settings)],
) -> TemporaryChatResponse:
    service = TemporaryChatService(redis, settings)
    await service.enforce_limits(
        client_ip=request.client.host if request.client else "unknown",
        temp_session_id=payload.temp_session_id,
    )
    turn = await service.send_turn(
        temp_session_id=payload.temp_session_id,
        temp_token=payload.temp_token,
        content=payload.content,
    )
    return TemporaryChatResponse(
        assistant_message=turn.assistant_message,
        temp_token=turn.issued_token,
        context_message_count=turn.context_message_count,
        expires_in_seconds=settings.temporary_chat_ttl_seconds,
    )
