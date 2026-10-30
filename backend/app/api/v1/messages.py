import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import TripPlanner, TripPlanningFailure
from app.agents.llm import intent_failure_log_fields
from app.core.dependencies import (
    AuthContext,
    get_auth_context,
    get_db_session,
    get_trip_planner,
    require_csrf,
)
from app.core.exceptions import AppError
from app.schemas.message import MessageCreateRequest, MessageResponse, MessageTurnResponse
from app.services.chat_service import ChatService

router = APIRouter(prefix="/conversations/{conversation_id}/messages", tags=["messages"])
logger = logging.getLogger(__name__)


@router.post("", response_model=MessageTurnResponse, status_code=status.HTTP_201_CREATED)
async def post_message(
    conversation_id: UUID,
    payload: MessageCreateRequest,
    request: Request,
    context: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    planner: Annotated[TripPlanner, Depends(get_trip_planner)],
) -> MessageTurnResponse:
    try:
        turn = await ChatService(db, planner).append_turn(
            conversation_id=conversation_id,
            owner_id=context.user.id,
            content=payload.content,
        )
    except TripPlanningFailure as exc:
        await db.rollback()
        logger.warning(
            "Trip planning request failed",
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
    return MessageTurnResponse(
        user_message=MessageResponse.model_validate(turn.user_message),
        assistant_message=MessageResponse.model_validate(turn.assistant_message),
        trip=turn.trip,
    )


@router.get("", response_model=list[MessageResponse])
async def list_messages(
    conversation_id: UUID,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=50)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MessageResponse]:
    messages = await ChatService(db).list_messages(
        conversation_id=conversation_id,
        owner_id=context.user.id,
        limit=limit,
        offset=offset,
    )
    return [MessageResponse.model_validate(item) for item in messages]
